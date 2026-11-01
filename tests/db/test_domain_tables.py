import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from app.database import Base
from app.models import (
    Alert,
    Chunk,
    CohortStat,
    Conversation,
    DeviceCycle,
    Document,
    ForecastSnapshot,
    IngestBatch,
    IngestCheckpoint,
    Message,
    SavingsMeasure,
    Suggestion,
    SuggestionFeedback,
    ToolCall,
)
from app.models.insight import MIN_COHORT_HOMES
from app.services.aggregates import backfill_aggregates as backfill
from tests.db.conftest import _create_migrated_db, run_alembic

LOCK_TIMEOUT = {"server_settings": {"lock_timeout": "5000"}}
NOW = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
T0 = datetime(2026, 10, 1, tzinfo=UTC)
T1 = T0 + timedelta(minutes=10)


def vec(i: int, dim: int = 1024) -> list[float]:
    v = [0.0] * dim
    v[i] = 1.0
    return v


def lit(v: list[float]) -> str:
    return "[" + ",".join(str(x) for x in v) + "]"


async def mk_home(c) -> uuid.UUID:
    return await c.scalar(text("INSERT INTO core.home (name) VALUES ('H') RETURNING id"))


async def mk_user(c) -> uuid.UUID:
    return await c.scalar(
        text("INSERT INTO users (id, email) VALUES (gen_random_uuid(), :e) RETURNING id"),
        {"e": f"{uuid.uuid4().hex}@example.com"},
    )


async def mk_device(c, home_id) -> uuid.UUID:
    return await c.scalar(
        text(
            "INSERT INTO core.device (home_id, device_type_code, name, origin) "
            "VALUES (:h, 'fridge', 'Fridge', 'nilm') RETURNING id"
        ),
        {"h": home_id},
    )


async def mk_series(c, home_id) -> int:
    return await c.scalar(
        text(
            "INSERT INTO energy.series (home_id, kind, metric, unit) "
            "VALUES (:h, 'main', 'power_w', 'W') RETURNING series_id"
        ),
        {"h": home_id},
    )


async def mk_alert(c, home_id, device_id=None) -> uuid.UUID:
    return await c.scalar(
        text(
            "INSERT INTO insight.alert (home_id, device_id, kind, severity, ts) "
            "VALUES (:h, :d, 'long_run', 'info', now()) RETURNING id"
        ),
        {"h": home_id, "d": device_id},
    )


async def mk_suggestion(c, home_id, device_id=None, alert_id=None) -> uuid.UUID:
    return await c.scalar(
        text(
            "INSERT INTO copilot.suggestion (home_id, device_id, alert_id, kind, title, body) "
            "VALUES (:h, :d, :a, 'k', 't', 'b') RETURNING id"
        ),
        {"h": home_id, "d": device_id, "a": alert_id},
    )


async def mk_document(c) -> uuid.UUID:
    return await c.scalar(
        text(
            "INSERT INTO knowledge.document (title, doc_type) VALUES ('D', 'guide') RETURNING id"
        )
    )


async def mk_chunk(c, doc_id, ord_, body="x", vector=None) -> int:
    return await c.scalar(
        text(
            "INSERT INTO knowledge.chunk (document_id, ord, body, embedding, embedding_model) "
            "VALUES (:d, :o, :b, CAST(:v AS vector), 'm') RETURNING id"
        ),
        {"d": doc_id, "o": ord_, "b": body, "v": lit(vector or vec(0))},
    )


async def count(c, table: str, where: str = "true", **params) -> int:
    return await c.scalar(text(f"SELECT count(*) FROM {table} WHERE {where}"), params)


async def rejected(db, sql: str, /, **params) -> None:
    """The statement must violate a constraint; run in a savepoint so `db` stays usable."""
    sp = await db.begin_nested()
    with pytest.raises(IntegrityError):
        await db.execute(text(sql), params)
    await sp.rollback()


# --- cohort_stat ---


COHORT = (
    "INSERT INTO insight.cohort_stat (cohort_key, period, p10_w, p33_w, p66_w, p90_w, n_homes) "
    "VALUES ('k', '2026-10-01', 1, 2, 3, 4, :n)"
)


async def test_cohort_min_size_check(conn):
    assert MIN_COHORT_HOMES == 10
    await rejected(conn, COHORT, n=9)
    await conn.execute(text(COHORT), {"n": 10})
    assert await count(conn, "insight.cohort_stat") == 1


# --- knowledge ---


async def test_chunk_fts_matches_unaccented_vietnamese(conn):
    doc = await mk_document(conn)
    await mk_chunk(conn, doc, 1, "Tiết kiệm điện")
    await mk_chunk(conn, doc, 2, "Điều hòa nhiệt độ", vec(1))
    query = "tiet kiem dien"
    hits = (
        await conn.execute(
            text(
                "SELECT ord FROM knowledge.chunk WHERE tsv @@ "
                "plainto_tsquery('simple', knowledge.immutable_unaccent(:q))"
            ),
            {"q": query},
        )
    ).scalars().all()
    assert hits == [1]
    # d-stroke is folded too
    assert await conn.scalar(text("SELECT knowledge.immutable_unaccent('Đđ')")) == "Dd"
    assert await conn.scalar(
        text("SELECT tsv @@ plainto_tsquery('simple', 'dieu') FROM knowledge.chunk "
             "WHERE ord = 2")
    )


async def test_chunk_hnsw_nearest(conn):
    indexdef = await conn.scalar(
        text(
            "SELECT indexdef FROM pg_indexes WHERE schemaname = 'knowledge' "
            "AND tablename = 'chunk' AND indexname = 'ix_chunk_embedding'"
        )
    )
    assert indexdef and "hnsw" in indexdef and "vector_cosine_ops" in indexdef
    assert "m='16'" in indexdef and "ef_construction='64'" in indexdef
    doc = await mk_document(conn)
    for i in range(5):
        await mk_chunk(conn, doc, i, f"c{i}", vec(i))
    near = [0.0] * 1024
    near[3], near[4] = 0.9, 0.1
    top = await conn.scalar(
        text(
            "SELECT ord FROM knowledge.chunk "
            "ORDER BY embedding <=> CAST(:v AS vector) LIMIT 1"
        ),
        {"v": lit(near)},
    )
    assert top == 3


async def test_chunk_unique_ord_and_not_null_embedding(conn):
    doc = await mk_document(conn)
    await mk_chunk(conn, doc, 1)
    await rejected(
        conn,
        "INSERT INTO knowledge.chunk (document_id, ord, body, embedding, embedding_model) "
        "VALUES (:d, 1, 'x', CAST(:v AS vector), 'm')",
        d=doc, v=lit(vec(0)),
    )
    await rejected(
        conn,
        "INSERT INTO knowledge.chunk (document_id, ord, body, embedding_model) "
        "VALUES (:d, 2, 'x', 'm')",
        d=doc,
    )


async def test_delete_document_removes_chunks(conn):
    doc = await mk_document(conn)
    await mk_chunk(conn, doc, 1)
    await conn.execute(text("DELETE FROM knowledge.document WHERE id = :d"), {"d": doc})
    assert await count(conn, "knowledge.chunk") == 0


# --- device_cycle ---


async def test_device_cycle_is_hypertable_with_30_day_chunks(conn):
    row = (
        await conn.execute(
            text(
                "SELECT d.column_name, d.time_interval FROM timescaledb_information.dimensions d "
                "WHERE d.hypertable_schema = 'insight' AND d.hypertable_name = 'device_cycle'"
            )
        )
    ).one()
    assert row.column_name == "start_ts"
    assert row.time_interval == timedelta(days=30)


async def test_device_cycle_check_pk_and_cascade(conn):
    h = await mk_home(conn)
    d = await mk_device(conn, h)
    sql = (
        "INSERT INTO insight.device_cycle "
        "(home_id, device_id, start_ts, end_ts, energy_wh, peak_w) "
        "VALUES (:h, :d, CAST(:s AS timestamptz), CAST(:e AS timestamptz), 5, 100)"
    )
    await rejected(conn, sql, h=h, d=d, s=T0, e=T0)
    await rejected(conn, sql, h=h, d=d, s=T0, e=T0 - timedelta(days=1))
    await conn.execute(text(sql), {"h": h, "d": d, "s": T0, "e": T1})
    await rejected(conn, sql, h=h, d=d, s=T0, e=T1)  # duplicate PK
    await conn.execute(text("DELETE FROM core.device WHERE id = :d"), {"d": d})
    assert await count(conn, "insight.device_cycle") == 0


# --- ops ---


async def test_ingest_checkpoint_pk(conn):
    h = await mk_home(conn)
    s = await mk_series(conn, h)
    sql = (
        "INSERT INTO ops.ingest_checkpoint (source, series_id, last_ts) "
        "VALUES (:src, :s, now())"
    )
    await conn.execute(text(sql), {"src": "csv", "s": s})
    await conn.execute(text(sql), {"src": "mqtt", "s": s})
    await rejected(conn, sql, src="csv", s=s)
    await conn.execute(text("DELETE FROM energy.series WHERE series_id = :s"), {"s": s})
    assert await count(conn, "ops.ingest_checkpoint") == 0


async def test_ingest_batch_defaults_and_home_set_null(conn):
    h = await mk_home(conn)
    bid = await conn.scalar(
        text("INSERT INTO ops.ingest_batch (source, home_id) VALUES ('csv', :h) RETURNING id"),
        {"h": h},
    )
    row = (
        await conn.execute(
            text("SELECT status, rows_in, rows_new, rows_dup, rows_bad, started_at "
                 "FROM ops.ingest_batch WHERE id = :i"),
            {"i": bid},
        )
    ).one()
    assert (row.status, row.rows_in, row.rows_new, row.rows_dup, row.rows_bad) == (
        "running", 0, 0, 0, 0,
    )
    assert row.started_at is not None
    await conn.execute(text("DELETE FROM core.home WHERE id = :h"), {"h": h})
    assert await conn.scalar(
        text("SELECT home_id FROM ops.ingest_batch WHERE id = :i"), {"i": bid}
    ) is None


# --- CHECK vocabularies ---


async def _alert(c, h, **over):
    cols = {"severity": "info", "status": "open", **over}
    return (
        "INSERT INTO insight.alert (home_id, kind, severity, status, ts) "
        f"VALUES (:h, 'k', '{cols['severity']}', '{cols['status']}', now())"
    )


@pytest.mark.parametrize("severity", ["info", "warning", "critical"])
async def test_alert_severity_accepted(conn, severity):
    h = await mk_home(conn)
    await conn.execute(text(await _alert(conn, h, severity=severity)), {"h": h})


async def test_alert_severity_rejected(conn):
    h = await mk_home(conn)
    await rejected(conn, await _alert(conn, h, severity="fatal"), h=h)


@pytest.mark.parametrize("status", ["open", "acknowledged", "resolved"])
async def test_alert_status_accepted(conn, status):
    h = await mk_home(conn)
    await conn.execute(text(await _alert(conn, h, status=status)), {"h": h})


async def test_alert_status_rejected(conn):
    h = await mk_home(conn)
    await rejected(conn, await _alert(conn, h, status="closed"), h=h)


async def test_message_role_check(conn):
    h = await mk_home(conn)
    u = await mk_user(conn)
    cid = await conn.scalar(
        text("INSERT INTO copilot.conversation (home_id, user_id) VALUES (:h, :u) RETURNING id"),
        {"h": h, "u": u},
    )
    sql = "INSERT INTO copilot.message (conversation_id, role, content) VALUES (:c, :r, 'x')"
    for role in ("user", "assistant", "tool", "system"):
        await conn.execute(text(sql), {"c": cid, "r": role})
    await rejected(conn, sql, c=cid, r="bot")


async def test_suggestion_status_check(conn):
    h = await mk_home(conn)
    sql = (
        "INSERT INTO copilot.suggestion (home_id, kind, title, body, status) "
        "VALUES (:h, 'k', 't', 'b', :s)"
    )
    for status in ("proposed", "shown", "accepted", "dismissed", "done"):
        await conn.execute(text(sql), {"h": h, "s": status})
    await rejected(conn, sql, h=h, s="pending")
    default = await conn.scalar(
        text("INSERT INTO copilot.suggestion (home_id, kind, title, body) "
             "VALUES (:h, 'k', 't', 'b') RETURNING status"),
        {"h": h},
    )
    assert default == "proposed"


async def test_suggestion_feedback_action_check(conn):
    h = await mk_home(conn)
    u = await mk_user(conn)
    sid = await mk_suggestion(conn, h)
    sql = (
        "INSERT INTO copilot.suggestion_feedback (suggestion_id, user_id, action) "
        "VALUES (:s, :u, :a)"
    )
    for action in ("accept", "ignore", "done", "dislike"):
        await conn.execute(text(sql), {"s": sid, "u": u, "a": action})
    await rejected(conn, sql, s=sid, u=u, a="love")


async def test_document_type_check(conn):
    sql = "INSERT INTO knowledge.document (title, doc_type) VALUES ('t', :t)"
    for t in ("standard", "guide", "tariff", "expert_rule", "other"):
        await conn.execute(text(sql), {"t": t})
    await rejected(conn, sql, t="blog")
    assert await conn.scalar(
        text("INSERT INTO knowledge.document (title, doc_type) VALUES ('t', 'other') "
             "RETURNING lang")
    ) == "vi"


async def test_ingest_batch_status_check(conn):
    sql = "INSERT INTO ops.ingest_batch (source, status) VALUES ('s', :s)"
    for s in ("running", "ok", "failed"):
        await conn.execute(text(sql), {"s": s})
    await rejected(conn, sql, s="done")


async def test_forecast_snapshot_unique(conn):
    h = await mk_home(conn)
    sql = (
        "INSERT INTO insight.forecast_snapshot "
        "(home_id, generated_at, horizon_date, kwh, amount, model_version) "
        "VALUES (:h, '2026-11-01T00:00Z', '2026-11-30', 100, 200000, 'v1')"
    )
    await conn.execute(text(sql), {"h": h})
    await rejected(conn, sql, h=h)


# --- cascades ---


async def test_delete_home_cascades(conn):
    h = await mk_home(conn)
    u = await mk_user(conn)
    a = await mk_alert(conn, h)
    cid = await conn.scalar(
        text("INSERT INTO copilot.conversation (home_id, user_id) VALUES (:h, :u) RETURNING id"),
        {"h": h, "u": u},
    )
    mid = await conn.scalar(
        text("INSERT INTO copilot.message (conversation_id, role, content) "
             "VALUES (:c, 'user', 'x') RETURNING id"),
        {"c": cid},
    )
    await conn.execute(
        text("INSERT INTO copilot.tool_call (message_id, tool, ok) VALUES (:m, 't', true)"),
        {"m": mid},
    )
    sid = await mk_suggestion(conn, h, alert_id=a)
    await conn.execute(
        text("INSERT INTO copilot.suggestion_feedback (suggestion_id, user_id, action) "
             "VALUES (:s, :u, 'accept')"),
        {"s": sid, "u": u},
    )
    await conn.execute(
        text("INSERT INTO copilot.savings_measure "
             "(suggestion_id, baseline_kwh, actual_kwh, measured_at) VALUES (:s, 10, 8, now())"),
        {"s": sid},
    )
    await conn.execute(text("DELETE FROM core.home WHERE id = :h"), {"h": h})
    for table in ("insight.alert", "copilot.conversation", "copilot.message",
                  "copilot.tool_call", "copilot.suggestion", "copilot.suggestion_feedback",
                  "copilot.savings_measure"):
        assert await count(conn, table) == 0, table
    assert await count(conn, "public.users", "id = :u", u=u) == 1


async def test_delete_user_cascades_conversation_and_feedback(conn):
    h = await mk_home(conn)
    u = await mk_user(conn)
    sid = await mk_suggestion(conn, h)
    await conn.execute(
        text("INSERT INTO copilot.conversation (home_id, user_id) VALUES (:h, :u)"),
        {"h": h, "u": u},
    )
    await conn.execute(
        text("INSERT INTO copilot.suggestion_feedback (suggestion_id, user_id, action) "
             "VALUES (:s, :u, 'ignore')"),
        {"s": sid, "u": u},
    )
    await conn.execute(text("DELETE FROM public.users WHERE id = :u"), {"u": u})
    assert await count(conn, "copilot.conversation") == 0
    assert await count(conn, "copilot.suggestion_feedback") == 0
    assert await count(conn, "copilot.suggestion") == 1


async def test_delete_device_sets_null(conn):
    h = await mk_home(conn)
    d = await mk_device(conn, h)
    a = await mk_alert(conn, h, d)
    s = await mk_suggestion(conn, h, device_id=d)
    await conn.execute(text("DELETE FROM core.device WHERE id = :d"), {"d": d})
    assert await conn.scalar(
        text("SELECT device_id FROM insight.alert WHERE id = :a"), {"a": a}
    ) is None
    assert await conn.scalar(
        text("SELECT device_id FROM copilot.suggestion WHERE id = :s"), {"s": s}
    ) is None


async def test_delete_alert_sets_suggestion_alert_null(conn):
    h = await mk_home(conn)
    a = await mk_alert(conn, h)
    s = await mk_suggestion(conn, h, alert_id=a)
    await conn.execute(text("DELETE FROM insight.alert WHERE id = :a"), {"a": a})
    assert await conn.scalar(
        text("SELECT alert_id FROM copilot.suggestion WHERE id = :s"), {"s": s}
    ) is None


# --- ORM ---


async def test_orm_round_trip_every_model(session):
    c = await session.connection()
    h = await mk_home(c)
    u = await mk_user(c)
    d = await mk_device(c, h)
    s = await mk_series(c, h)

    t0 = NOW
    alert = Alert(home_id=h, device_id=d, kind="long_run", severity="warning", ts=t0,
                  payload={"minutes": 13})
    cycle = DeviceCycle(home_id=h, device_id=d, start_ts=t0, end_ts=t0 + timedelta(minutes=13),
                        energy_wh=42.5, peak_w=1200.0)
    forecast = ForecastSnapshot(home_id=h, generated_at=t0, horizon_date=date(2026, 11, 30),
                                kwh=Decimal("123.456"), amount=Decimal("345678.90"),
                                tier_cross_date=date(2026, 11, 20), model_version="v1")
    cohort = CohortStat(cohort_key="hcm-apt", period=date(2026, 10, 1), p10_w=Decimal("1.5"),
                        p33_w=Decimal("2.5"), p66_w=Decimal("3.5"), p90_w=Decimal("4.5"),
                        n_homes=12)
    conv = Conversation(home_id=h, user_id=u, title="hi")
    session.add_all([alert, cycle, forecast, cohort, conv])
    await session.flush()
    msg = Message(conversation_id=conv.id, role="assistant", content="hello")
    sug = Suggestion(home_id=h, device_id=d, alert_id=alert.id, kind="shift", title="t",
                     body="b", expected_kwh=Decimal("1.5"), expected_amount=Decimal("4500"))
    doc = Document(title="Guide", doc_type="guide", published_at=date(2026, 1, 1))
    batch = IngestBatch(source="csv", home_id=h, rows_in=3)
    ckpt = IngestCheckpoint(source="csv", series_id=s, last_ts=t0)
    session.add_all([msg, sug, doc, batch, ckpt])
    await session.flush()
    call = ToolCall(message_id=msg.id, tool="sql", input={"q": 1}, sql_text="select 1",
                    unit="kWh", duration_ms=5, ok=True)
    fb = SuggestionFeedback(suggestion_id=sug.id, user_id=u, action="accept", note="n")
    sm = SavingsMeasure(suggestion_id=sug.id, baseline_kwh=Decimal("10"),
                        actual_kwh=Decimal("8"), measured_at=t0)
    chunk = Chunk(document_id=doc.id, ord=1, body="Tiết kiệm điện", embedding=vec(7),
                  embedding_model="m", token_count=4)
    session.add_all([call, fb, sm, chunk])
    await session.flush()
    session.expire_all()

    got = (await session.execute(select(Alert))).scalar_one()
    assert got.payload == {"minutes": 13} and got.status == "open"
    assert (await session.execute(select(DeviceCycle))).scalar_one().energy_wh == 42.5
    assert (await session.execute(select(ForecastSnapshot))).scalar_one().kwh == Decimal("123.456")
    assert (await session.execute(select(CohortStat))).scalar_one().n_homes == 12
    assert (await session.execute(select(Conversation))).scalar_one().created_at is not None
    assert (await session.execute(select(Message))).scalar_one().content == "hello"
    assert (await session.execute(select(ToolCall))).scalar_one().input == {"q": 1}
    assert (await session.execute(select(Suggestion))).scalar_one().status == "proposed"
    assert (await session.execute(select(SuggestionFeedback))).scalar_one().action == "accept"
    assert (await session.execute(select(SavingsMeasure))).scalar_one().method == "M&V"
    assert (await session.execute(select(Document))).scalar_one().lang == "vi"
    chunk_row = (await session.execute(select(Chunk))).scalar_one()
    assert chunk_row.tsv == "'dien':3 'kiem':2 'tiet':1"
    assert list(chunk_row.embedding)[7] == 1.0
    assert (await session.execute(select(IngestBatch))).scalar_one().status == "running"
    assert (await session.execute(select(IngestCheckpoint))).scalar_one().updated_at is not None


def test_metadata_sorted_tables_resolve():
    names = {t.fullname for t in Base.metadata.sorted_tables}
    expected = {
        "insight.device_cycle", "insight.alert", "insight.forecast_snapshot",
        "insight.cohort_stat", "copilot.conversation", "copilot.message", "copilot.tool_call",
        "copilot.suggestion", "copilot.suggestion_feedback", "copilot.savings_measure",
        "knowledge.document", "knowledge.chunk", "ops.ingest_batch", "ops.ingest_checkpoint",
    }
    assert expected <= names
    order = [t.fullname for t in Base.metadata.sorted_tables]
    assert order.index("insight.alert") < order.index("copilot.suggestion")


# --- ops views ---


@pytest.fixture(scope="module")
async def vdb():
    """Private migrated database (policies off); yields an AUTOCOMMIT connection."""
    dsn, drop = await _create_migrated_db()
    engine = create_async_engine(dsn, isolation_level="AUTOCOMMIT", connect_args=LOCK_TIMEOUT)
    try:
        async with engine.connect() as c:
            await c.execute(text("SELECT ops.set_policies(false)"))
            yield c
    finally:
        await engine.dispose()
        await drop()


async def test_series_daily_coverage_view(vdb):
    c = vdb
    h = await mk_home(c)
    s = await mk_series(c, h)
    start = datetime(2026, 10, 9, 17, 0, tzinfo=UTC)  # 2026-10-10 00:00 local
    await c.execute(
        text(
            "INSERT INTO energy.reading (ts, series_id, value) "
            "SELECT CAST(:s AS timestamptz) + g * interval '1 minute', :sid, 100 "
            "FROM generate_series(0, 719) g"
        ),
        {"s": start, "sid": s},
    )
    await backfill(c, start - timedelta(days=1), start + timedelta(days=3))
    row = (
        await c.execute(
            text("SELECT day, covered_minutes, expected_minutes, coverage "
                 "FROM ops.series_daily_coverage WHERE series_id = :s"),
            {"s": s},
        )
    ).one()
    assert row.day == date(2026, 10, 10)
    assert row.covered_minutes == 720 and row.expected_minutes == 1440
    assert row.coverage == Decimal("0.5")


async def test_stale_series_view(vdb):
    c = vdb
    h = await mk_home(c)
    fresh = await mk_series(c, h)
    d1, d2 = await mk_device(c, h), await mk_device(c, h)
    ids = []
    for d in (d1, d2):
        ids.append(await c.scalar(
            text("INSERT INTO energy.series (home_id, kind, device_id, metric, unit) "
                 "VALUES (:h, 'device', :d, 'power_w', 'W') RETURNING series_id"),
            {"h": h, "d": d},
        ))
    stale, old = ids
    insert = (
        "INSERT INTO ops.ingest_checkpoint (source, series_id, last_ts) "
        "VALUES (:src, :s, now() - CAST(:age AS interval))"
    )
    await c.execute(text(insert), {"src": "a", "s": fresh, "age": timedelta(minutes=10)})
    await c.execute(text(insert), {"src": "a", "s": stale, "age": timedelta(hours=3)})
    # a second, fresher source for `old` keeps it out of the view
    await c.execute(text(insert), {"src": "a", "s": old, "age": timedelta(hours=5)})
    await c.execute(text(insert), {"src": "b", "s": old, "age": timedelta(minutes=1)})
    rows = {
        r.series_id: r.minutes_since
        for r in await c.execute(
            text("SELECT series_id, minutes_since FROM ops.stale_series "
                 "WHERE series_id = ANY(:ids)"),
            {"ids": [fresh, stale, old]},
        )
    }
    assert set(rows) == {stale}
    assert 179 <= rows[stale] <= 181


# --- migration round trip ---


async def test_domain_tables_downgrade_upgrade(throwaway_dsn):
    tables = text(
        "SELECT count(*) FROM information_schema.tables WHERE table_type = 'BASE TABLE' "
        "AND table_schema IN ('insight','copilot','knowledge','ops')"
    )
    views = text(
        "SELECT count(*) FROM information_schema.views WHERE table_schema = 'ops'"
    )
    func = text(
        "SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
        "WHERE n.nspname = 'knowledge' AND p.proname = 'immutable_unaccent'"
    )
    engine = create_async_engine(
        throwaway_dsn, isolation_level="AUTOCOMMIT", connect_args=LOCK_TIMEOUT
    )
    try:
        async with engine.connect() as c:
            # ops.set_policies is a function, not a table: only the 14 new ones count here
            assert await c.scalar(tables) == 14 and await c.scalar(views) == 2
            assert await c.scalar(func) == 1
        run_alembic(throwaway_dsn, "downgrade", "d7b3f9a2c6e4")
        async with engine.connect() as c:
            assert await c.scalar(tables) == 0 and await c.scalar(views) == 0
            assert await c.scalar(func) == 0
        run_alembic(throwaway_dsn, "upgrade", "head")
        async with engine.connect() as c:
            assert await c.scalar(tables) == 14 and await c.scalar(views) == 2
            assert await c.scalar(func) == 1
    finally:
        await engine.dispose()
