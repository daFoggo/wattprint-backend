import re
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


async def mk_home(c) -> int:
    return await c.scalar(text("INSERT INTO public.tb_home (name) VALUES ('H') RETURNING id"))


async def mk_user(c) -> int:
    return await c.scalar(
        text("INSERT INTO tb_users (email) VALUES (:e) RETURNING id"),
        {"e": f"{uuid.uuid4().hex}@example.com"},
    )


async def mk_device(c, home_id) -> int:
    return await c.scalar(
        text(
            "INSERT INTO public.tb_device (home_id, device_type_code, name, origin) "
            "VALUES (:h, 'fridge', 'Fridge', 'nilm') RETURNING id"
        ),
        {"h": home_id},
    )


async def mk_series(c, home_id) -> int:
    return await c.scalar(
        text(
            "INSERT INTO public.tb_series (home_id, kind, metric, unit) "
            "VALUES (:h, 'main', 'power_w', 'W') RETURNING series_id"
        ),
        {"h": home_id},
    )


async def mk_alert(c, home_id, device_id=None) -> int:
    return await c.scalar(
        text(
            "INSERT INTO public.tb_alert (home_id, device_id, kind, severity, ts) "
            "VALUES (:h, :d, 'long_run', 'info', now()) RETURNING id"
        ),
        {"h": home_id, "d": device_id},
    )


async def mk_suggestion(c, home_id, device_id=None, alert_id=None) -> int:
    return await c.scalar(
        text(
            "INSERT INTO public.tb_suggestion (home_id, device_id, alert_id, kind, title, body) "
            "VALUES (:h, :d, :a, 'k', 't', 'b') RETURNING id"
        ),
        {"h": home_id, "d": device_id, "a": alert_id},
    )


async def mk_document(c) -> int:
    return await c.scalar(
        text(
            "INSERT INTO public.tb_document (title, doc_type) VALUES ('D', 'guide') RETURNING id"
        )
    )


async def mk_chunk(c, doc_id, ord_, body="x", vector=None) -> int:
    return await c.scalar(
        text(
            "INSERT INTO public.tb_chunk (document_id, ord, body, embedding, embedding_model) "
            "VALUES (:d, :o, :b, CAST(:v AS vector), 'm') RETURNING id"
        ),
        {"d": doc_id, "o": ord_, "b": body, "v": lit(vector or vec(0))},
    )


async def count(c, table: str, where: str = "true", **params) -> int:
    return await c.scalar(text(f"SELECT count(*) FROM {table} WHERE {where}"), params)


async def rejected(db, sql: str, /, constraint: str, **params) -> None:
    """The statement must fail on exactly the named constraint (savepoint keeps `db` usable)."""
    sp = await db.begin_nested()
    with pytest.raises(IntegrityError) as exc:
        await db.execute(text(sql), params)
    cause = exc.value.orig.__cause__
    if constraint.startswith("not_null:"):  # NOT NULL violations carry a column, not a name
        assert cause.column_name == constraint.removeprefix("not_null:")
    else:
        # hypertable chunks prefix the constraint name with their own id (e.g. "3_pk_x")
        assert re.fullmatch(rf"(\d+_)*{constraint}", cause.constraint_name or ""), (
            cause.constraint_name
        )
    await sp.rollback()


# --- cohort_stat ---


COHORT = (
    "INSERT INTO public.tb_cohort_stat (cohort_key, period, p10_w, p33_w, p66_w, p90_w, n_homes) "
    "VALUES ('k', '2026-10-01', 1, 2, 3, 4, :n)"
)


async def test_cohort_min_size_check(conn):
    assert MIN_COHORT_HOMES == 10
    await rejected(conn, COHORT, "ck_cohort_stat_min_size", n=9)
    await conn.execute(text(COHORT), {"n": 10})
    assert await count(conn, "public.tb_cohort_stat") == 1


# --- knowledge ---


async def test_chunk_fts_matches_unaccented_vietnamese(conn):
    doc = await mk_document(conn)
    await mk_chunk(conn, doc, 1, "Tiết kiệm điện")
    await mk_chunk(conn, doc, 2, "Điều hòa nhiệt độ", vec(1))
    query = "tiet kiem dien"
    hits = (
        (
            await conn.execute(
                text(
                    "SELECT ord FROM public.tb_chunk WHERE tsv @@ "
                    "plainto_tsquery('simple', public.immutable_unaccent(:q))"
                ),
                {"q": query},
            )
        )
        .scalars()
        .all()
    )
    assert hits == [1]
    # d-stroke is folded too
    assert await conn.scalar(text("SELECT public.immutable_unaccent('Đđ')")) == "Dd"
    assert await conn.scalar(
        text(
            "SELECT tsv @@ plainto_tsquery('simple', 'dieu') FROM public.tb_chunk WHERE ord = 2"
        )
    )


async def test_chunk_hnsw_index_exists_and_nearest_is_correct(conn):
    indexdef = await conn.scalar(
        text(
            "SELECT indexdef FROM pg_indexes WHERE schemaname = 'public' "
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
            "SELECT ord FROM public.tb_chunk ORDER BY embedding <=> CAST(:v AS vector) LIMIT 1"
        ),
        {"v": lit(near)},
    )
    assert top == 3


async def test_chunk_unique_ord_and_not_null_embedding(conn):
    doc = await mk_document(conn)
    await mk_chunk(conn, doc, 1)
    await rejected(
        conn,
        "INSERT INTO public.tb_chunk (document_id, ord, body, embedding, embedding_model) "
        "VALUES (:d, 1, 'x', CAST(:v AS vector), 'm')",
        "uq_chunk_document_id",
        d=doc,
        v=lit(vec(0)),
    )
    await rejected(
        conn,
        "INSERT INTO public.tb_chunk (document_id, ord, body, embedding_model) "
        "VALUES (:d, 2, 'x', 'm')",
        "not_null:embedding",
        d=doc,
    )


async def test_delete_document_removes_chunks(conn):
    doc = await mk_document(conn)
    await mk_chunk(conn, doc, 1)
    await conn.execute(text("DELETE FROM public.tb_document WHERE id = :d"), {"d": doc})
    assert await count(conn, "public.tb_chunk") == 0


# --- device_cycle ---


async def test_device_cycle_is_hypertable_with_30_day_chunks(conn):
    row = (
        await conn.execute(
            text(
                "SELECT d.column_name, d.time_interval FROM timescaledb_information.dimensions d "
                "WHERE d.hypertable_schema = 'public' AND d.hypertable_name = 'tb_device_cycle'"
            )
        )
    ).one()
    assert row.column_name == "start_ts"
    assert row.time_interval == timedelta(days=30)


async def test_device_cycle_check_pk_and_cascade(conn):
    h = await mk_home(conn)
    d = await mk_device(conn, h)
    sql = (
        "INSERT INTO public.tb_device_cycle "
        "(home_id, device_id, start_ts, end_ts, energy_wh, peak_w) "
        "VALUES (:h, :d, CAST(:s AS timestamptz), CAST(:e AS timestamptz), 5, 100)"
    )
    await rejected(conn, sql, "ck_device_cycle_range", h=h, d=d, s=T0, e=T0)
    await rejected(conn, sql, "ck_device_cycle_range", h=h, d=d, s=T0, e=T0 - timedelta(days=1))
    await conn.execute(text(sql), {"h": h, "d": d, "s": T0, "e": T1})
    await rejected(conn, sql, "pk_device_cycle", h=h, d=d, s=T0, e=T1)  # duplicate PK
    await conn.execute(text("DELETE FROM public.tb_device WHERE id = :d"), {"d": d})
    assert await count(conn, "public.tb_device_cycle") == 0


# --- ops ---


async def test_ingest_checkpoint_pk(conn):
    h = await mk_home(conn)
    s = await mk_series(conn, h)
    sql = (
        "INSERT INTO public.tb_ingest_checkpoint (source, series_id, last_ts) VALUES (:src, :s, now())"
    )
    await conn.execute(text(sql), {"src": "csv", "s": s})
    await conn.execute(text(sql), {"src": "mqtt", "s": s})
    await rejected(conn, sql, "pk_ingest_checkpoint", src="csv", s=s)
    await conn.execute(text("DELETE FROM public.tb_series WHERE series_id = :s"), {"s": s})
    assert await count(conn, "public.tb_ingest_checkpoint") == 0


async def test_ingest_batch_defaults_and_home_set_null(conn):
    h = await mk_home(conn)
    bid = await conn.scalar(
        text("INSERT INTO public.tb_ingest_batch (source, home_id) VALUES ('csv', :h) RETURNING id"),
        {"h": h},
    )
    row = (
        await conn.execute(
            text(
                "SELECT status, rows_in, rows_new, rows_dup, rows_bad, started_at "
                "FROM public.tb_ingest_batch WHERE id = :i"
            ),
            {"i": bid},
        )
    ).one()
    assert (row.status, row.rows_in, row.rows_new, row.rows_dup, row.rows_bad) == (
        "running",
        0,
        0,
        0,
        0,
    )
    assert row.started_at is not None
    await conn.execute(text("DELETE FROM public.tb_home WHERE id = :h"), {"h": h})
    assert (
        await conn.scalar(text("SELECT home_id FROM public.tb_ingest_batch WHERE id = :i"), {"i": bid})
        is None
    )


# --- CHECK vocabularies ---


def _alert(**over):
    cols = {"severity": "info", "status": "open", **over}
    return (
        "INSERT INTO public.tb_alert (home_id, kind, severity, status, ts) "
        f"VALUES (:h, 'k', '{cols['severity']}', '{cols['status']}', now())"
    )


@pytest.mark.parametrize("severity", ["info", "warning", "critical"])
async def test_alert_severity_accepted(conn, severity):
    h = await mk_home(conn)
    await conn.execute(text(_alert(severity=severity)), {"h": h})


async def test_alert_severity_rejected(conn):
    h = await mk_home(conn)
    await rejected(conn, _alert(severity="fatal"), "ck_alert_severity", h=h)


@pytest.mark.parametrize("status", ["open", "acknowledged", "resolved"])
async def test_alert_status_accepted(conn, status):
    h = await mk_home(conn)
    await conn.execute(text(_alert(status=status)), {"h": h})


async def test_alert_status_rejected(conn):
    h = await mk_home(conn)
    await rejected(conn, _alert(status="closed"), "ck_alert_status", h=h)


async def test_message_role_check(conn):
    h = await mk_home(conn)
    u = await mk_user(conn)
    cid = await conn.scalar(
        text("INSERT INTO ai.ai_conversation (home_id, user_id) VALUES (:h, :u) RETURNING id"),
        {"h": h, "u": u},
    )
    sql = "INSERT INTO ai.ai_message (conversation_id, role, content) VALUES (:c, :r, 'x')"
    for role in ("user", "assistant", "tool", "system"):
        await conn.execute(text(sql), {"c": cid, "r": role})
    await rejected(conn, sql, "ck_ai_message_role", c=cid, r="bot")


async def test_suggestion_status_check(conn):
    h = await mk_home(conn)
    sql = (
        "INSERT INTO public.tb_suggestion (home_id, kind, title, body, status) "
        "VALUES (:h, 'k', 't', 'b', :s)"
    )
    for status in ("proposed", "shown", "accepted", "dismissed", "done"):
        await conn.execute(text(sql), {"h": h, "s": status})
    await rejected(conn, sql, "ck_suggestion_status", h=h, s="pending")
    default = await conn.scalar(
        text(
            "INSERT INTO public.tb_suggestion (home_id, kind, title, body) "
            "VALUES (:h, 'k', 't', 'b') RETURNING status"
        ),
        {"h": h},
    )
    assert default == "proposed"


async def test_suggestion_feedback_action_check(conn):
    h = await mk_home(conn)
    u = await mk_user(conn)
    sid = await mk_suggestion(conn, h)
    sql = (
        "INSERT INTO public.tb_suggestion_feedback (suggestion_id, user_id, action) "
        "VALUES (:s, :u, :a)"
    )
    for action in ("accept", "ignore", "done", "dislike"):
        await conn.execute(text(sql), {"s": sid, "u": u, "a": action})
    await rejected(conn, sql, "ck_suggestion_feedback_action", s=sid, u=u, a="love")


async def test_document_type_check(conn):
    sql = "INSERT INTO public.tb_document (title, doc_type) VALUES ('t', :t)"
    for t in ("standard", "guide", "tariff", "expert_rule", "other"):
        await conn.execute(text(sql), {"t": t})
    await rejected(conn, sql, "ck_document_doc_type", t="blog")
    assert (
        await conn.scalar(
            text(
                "INSERT INTO public.tb_document (title, doc_type) VALUES ('t', 'other') "
                "RETURNING lang"
            )
        )
        == "vi"
    )


async def test_ingest_batch_status_check(conn):
    sql = "INSERT INTO public.tb_ingest_batch (source, status) VALUES ('s', :s)"
    for s in ("running", "ok", "failed"):
        await conn.execute(text(sql), {"s": s})
    await rejected(conn, sql, "ck_ingest_batch_status", s="done")


async def test_forecast_snapshot_unique(conn):
    h = await mk_home(conn)
    sql = (
        "INSERT INTO public.tb_forecast_snapshot "
        "(home_id, generated_at, horizon_date, kwh, amount, model_version) "
        "VALUES (:h, '2026-11-01T00:00Z', '2026-11-30', 100, 200000, 'v1')"
    )
    await conn.execute(text(sql), {"h": h})
    await rejected(conn, sql, "uq_forecast_snapshot_home_id", h=h)


# --- cascades ---


async def test_delete_home_cascades(conn):
    h = await mk_home(conn)
    u = await mk_user(conn)
    a = await mk_alert(conn, h)
    cid = await conn.scalar(
        text("INSERT INTO ai.ai_conversation (home_id, user_id) VALUES (:h, :u) RETURNING id"),
        {"h": h, "u": u},
    )
    mid = await conn.scalar(
        text(
            "INSERT INTO ai.ai_message (conversation_id, role, content) "
            "VALUES (:c, 'user', 'x') RETURNING id"
        ),
        {"c": cid},
    )
    await conn.execute(
        text("INSERT INTO ai.ai_tool_call (message_id, tool, ok) VALUES (:m, 't', true)"),
        {"m": mid},
    )
    sid = await mk_suggestion(conn, h, alert_id=a)
    await conn.execute(
        text(
            "INSERT INTO public.tb_suggestion_feedback (suggestion_id, user_id, action) "
            "VALUES (:s, :u, 'accept')"
        ),
        {"s": sid, "u": u},
    )
    await conn.execute(
        text(
            "INSERT INTO public.tb_savings_measure "
            "(suggestion_id, baseline_kwh, actual_kwh, measured_at) VALUES (:s, 10, 8, now())"
        ),
        {"s": sid},
    )
    await conn.execute(text("DELETE FROM public.tb_home WHERE id = :h"), {"h": h})
    for table in (
        "public.tb_alert",
        "ai.ai_conversation",
        "ai.ai_message",
        "ai.ai_tool_call",
        "public.tb_suggestion",
        "public.tb_suggestion_feedback",
        "public.tb_savings_measure",
    ):
        assert await count(conn, table) == 0, table
    assert await count(conn, "public.tb_users", "id = :u", u=u) == 1


async def test_delete_user_cascades_conversation_and_feedback(conn):
    h = await mk_home(conn)
    u = await mk_user(conn)
    sid = await mk_suggestion(conn, h)
    await conn.execute(
        text("INSERT INTO ai.ai_conversation (home_id, user_id) VALUES (:h, :u)"),
        {"h": h, "u": u},
    )
    await conn.execute(
        text(
            "INSERT INTO public.tb_suggestion_feedback (suggestion_id, user_id, action) "
            "VALUES (:s, :u, 'ignore')"
        ),
        {"s": sid, "u": u},
    )
    await conn.execute(text("DELETE FROM public.tb_users WHERE id = :u"), {"u": u})
    assert await count(conn, "ai.ai_conversation") == 0
    assert await count(conn, "public.tb_suggestion_feedback") == 0
    assert await count(conn, "public.tb_suggestion") == 1


async def test_delete_device_sets_null(conn):
    h = await mk_home(conn)
    d = await mk_device(conn, h)
    a = await mk_alert(conn, h, d)
    s = await mk_suggestion(conn, h, device_id=d)
    await conn.execute(text("DELETE FROM public.tb_device WHERE id = :d"), {"d": d})
    assert (
        await conn.scalar(text("SELECT device_id FROM public.tb_alert WHERE id = :a"), {"a": a})
        is None
    )
    assert (
        await conn.scalar(
            text("SELECT device_id FROM public.tb_suggestion WHERE id = :s"), {"s": s}
        )
        is None
    )


async def test_delete_alert_sets_suggestion_alert_null(conn):
    h = await mk_home(conn)
    a = await mk_alert(conn, h)
    s = await mk_suggestion(conn, h, alert_id=a)
    await conn.execute(text("DELETE FROM public.tb_alert WHERE id = :a"), {"a": a})
    assert (
        await conn.scalar(
            text("SELECT alert_id FROM public.tb_suggestion WHERE id = :s"), {"s": s}
        )
        is None
    )


# --- ORM ---


async def test_orm_round_trip_every_model(session):
    c = await session.connection()
    h = await mk_home(c)
    u = await mk_user(c)
    d = await mk_device(c, h)
    s = await mk_series(c, h)

    t0 = NOW
    alert = Alert(
        home_id=h, device_id=d, kind="long_run", severity="warning", ts=t0, payload={"minutes": 13}
    )
    cycle = DeviceCycle(
        home_id=h,
        device_id=d,
        start_ts=t0,
        end_ts=t0 + timedelta(minutes=13),
        energy_wh=42.5,
        peak_w=1200.0,
    )
    forecast = ForecastSnapshot(
        home_id=h,
        generated_at=t0,
        horizon_date=date(2026, 11, 30),
        kwh=Decimal("123.456"),
        amount=Decimal("345678.90"),
        tier_cross_date=date(2026, 11, 20),
        model_version="v1",
    )
    cohort = CohortStat(
        cohort_key="hcm-apt",
        period=date(2026, 10, 1),
        p10_w=Decimal("1.5"),
        p33_w=Decimal("2.5"),
        p66_w=Decimal("3.5"),
        p90_w=Decimal("4.5"),
        n_homes=12,
    )
    conv = Conversation(home_id=h, user_id=u, title="hi")
    session.add_all([alert, cycle, forecast, cohort, conv])
    await session.flush()
    msg = Message(conversation_id=conv.id, role="assistant", content="hello")
    sug = Suggestion(
        home_id=h,
        device_id=d,
        alert_id=alert.id,
        kind="shift",
        title="t",
        body="b",
        expected_kwh=Decimal("1.5"),
        expected_amount=Decimal("4500"),
    )
    doc = Document(title="Guide", doc_type="guide", published_at=date(2026, 1, 1))
    batch = IngestBatch(source="csv", home_id=h, rows_in=3)
    ckpt = IngestCheckpoint(source="csv", series_id=s, last_ts=t0)
    session.add_all([msg, sug, doc, batch, ckpt])
    await session.flush()
    call = ToolCall(
        message_id=msg.id,
        tool="sql",
        input={"q": 1},
        sql_text="select 1",
        unit="kWh",
        duration_ms=5,
        ok=True,
    )
    fb = SuggestionFeedback(suggestion_id=sug.id, user_id=u, action="accept", note="n")
    sm = SavingsMeasure(
        suggestion_id=sug.id, baseline_kwh=Decimal("10"), actual_kwh=Decimal("8"), measured_at=t0
    )
    chunk = Chunk(
        document_id=doc.id,
        ord=1,
        body="Tiết kiệm điện",
        embedding=vec(7),
        embedding_model="m",
        token_count=4,
    )
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
        "public.tb_device_cycle",
        "public.tb_alert",
        "public.tb_forecast_snapshot",
        "public.tb_cohort_stat",
        "ai.ai_conversation",
        "ai.ai_message",
        "ai.ai_tool_call",
        "public.tb_suggestion",
        "public.tb_suggestion_feedback",
        "public.tb_savings_measure",
        "public.tb_document",
        "public.tb_chunk",
        "public.tb_ingest_batch",
        "public.tb_ingest_checkpoint",
    }
    assert expected <= names
    order = [t.fullname for t in Base.metadata.sorted_tables]
    assert order.index("public.tb_alert") < order.index("public.tb_suggestion")


# --- ops views ---


@pytest.fixture(scope="module")
async def vdb():
    """Private migrated database (policies off); yields an AUTOCOMMIT connection."""
    dsn, drop = await _create_migrated_db()
    engine = create_async_engine(dsn, isolation_level="AUTOCOMMIT", connect_args=LOCK_TIMEOUT)
    try:
        async with engine.connect() as c:
            await c.execute(text("SELECT public.set_policies(false)"))
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
            "INSERT INTO public.tb_reading (ts, series_id, value) "
            "SELECT CAST(:s AS timestamptz) + g * interval '1 minute', :sid, 100 "
            "FROM generate_series(0, 719) g"
        ),
        {"s": start, "sid": s},
    )
    await backfill(c, start - timedelta(days=1), start + timedelta(days=3))
    row = (
        await c.execute(
            text(
                "SELECT day, covered_minutes, expected_minutes, coverage "
                "FROM public.series_daily_coverage WHERE series_id = :s AND day = '2026-10-10'"
            ),
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
    ids = []
    for d in [await mk_device(c, h) for _ in range(4)]:
        ids.append(
            await c.scalar(
                text(
                    "INSERT INTO public.tb_series (home_id, kind, device_id, metric, unit) "
                    "VALUES (:h, 'device', :d, 'power_w', 'W') RETURNING series_id"
                ),
                {"h": h, "d": d},
            )
        )
    stale, old, at59, at61 = ids
    insert = (
        "INSERT INTO public.tb_ingest_checkpoint (source, series_id, last_ts) "
        "VALUES (:src, :s, now() - CAST(:age AS interval))"
    )
    await c.execute(text(insert), {"src": "a", "s": fresh, "age": timedelta(minutes=10)})
    await c.execute(text(insert), {"src": "a", "s": stale, "age": timedelta(hours=3)})
    # a second, fresher source for `old` keeps it out of the view
    await c.execute(text(insert), {"src": "a", "s": old, "age": timedelta(hours=5)})
    await c.execute(text(insert), {"src": "b", "s": old, "age": timedelta(minutes=1)})
    await c.execute(text(insert), {"src": "a", "s": at59, "age": timedelta(minutes=59)})
    await c.execute(text(insert), {"src": "a", "s": at61, "age": timedelta(minutes=61)})
    rows = {
        r.series_id: r.minutes_since
        for r in await c.execute(
            text(
                "SELECT series_id, minutes_since FROM public.stale_series WHERE series_id = ANY(:ids)"
            ),
            {"ids": [fresh, stale, old, at59, at61]},
        )
    }
    assert set(rows) == {stale, at61}  # 59 minutes is fresh, 61 is stale
    assert rows[at61] == 61
    assert 179 <= rows[stale] <= 181


async def test_series_daily_coverage_lists_silent_days_as_zero(vdb):
    c = vdb
    h = await mk_home(c)
    s = await mk_series(c, h)
    silent = await c.scalar(  # never reported: no history, not listed
        text(
            "INSERT INTO public.tb_series (home_id, kind, device_id, metric, unit) "
            "VALUES (:h, 'device', :d, 'power_w', 'W') RETURNING series_id"
        ),
        {"h": h, "d": await mk_device(c, h)},
    )
    today_local = await c.scalar(text("SELECT (now() AT TIME ZONE 'Asia/Ho_Chi_Minh')::date"))
    first = today_local - timedelta(days=6)
    for offset in (0, 1, 2, 6):  # reports on days 1-3 and 7, silent on 4-6
        start = await c.scalar(
            text("SELECT CAST(:d AS timestamp) AT TIME ZONE 'Asia/Ho_Chi_Minh'"),
            {"d": datetime.combine(first + timedelta(days=offset), datetime.min.time())},
        )
        await c.execute(
            text(
                "INSERT INTO public.tb_reading (ts, series_id, value) "
                "SELECT CAST(:s AS timestamptz) + g * interval '1 minute', :sid, 100 "
                "FROM generate_series(0, 59) g"
            ),
            {"s": start, "sid": s},
        )
    now = datetime.now(UTC)
    await backfill(c, now - timedelta(days=10), now + timedelta(days=1))
    rows = (
        await c.execute(
            text(
                "SELECT day, covered_minutes, coverage FROM public.series_daily_coverage "
                "WHERE series_id = :s ORDER BY day"
            ),
            {"s": s},
        )
    ).all()
    assert [r.day for r in rows] == [first + timedelta(days=i) for i in range(7)]
    assert [r.covered_minutes for r in rows] == [60, 60, 60, 0, 0, 0, 60]
    assert rows[3].coverage == 0
    assert (
        await c.scalar(
            text("SELECT count(*) FROM public.series_daily_coverage WHERE series_id = :s"),
            {"s": silent},
        )
        == 0
    )


async def test_model_and_migration_indexes_agree(vdb):
    schemas = ("public",)
    in_db = {
        (r.schemaname, r.indexname)
        for r in await vdb.execute(
            text("SELECT schemaname, indexname FROM pg_indexes WHERE schemaname = ANY(:s)"),
            {"s": list(schemas)},
        )
    }
    declared = {
        (t.schema, i.name)
        for t in Base.metadata.sorted_tables
        if t.schema in schemas
        for i in t.indexes
    }
    assert declared <= in_db
    # no stray indexes in the database (PK / unique indexes back constraints, not model Indexes)
    backing = {
        (r.schemaname, r.indexname)
        for r in await vdb.execute(
            text(
                "SELECT n.nspname AS schemaname, c.conname AS indexname FROM pg_constraint c "
                "JOIN pg_namespace n ON n.oid = c.connamespace "
                "WHERE n.nspname = ANY(:s) AND c.contype IN ('p','u')"
            ),
            {"s": list(schemas)},
        )
    }
    assert in_db - declared - backing == set()


# --- migration round trip ---


async def test_domain_tables_downgrade_upgrade(throwaway_dsn):
    tables = text(
        "SELECT count(*) FROM information_schema.tables WHERE table_type = 'BASE TABLE' "
        "AND table_schema = 'public'"
    )
    views = text("SELECT count(*) FROM information_schema.views WHERE table_schema = 'public'")
    func = text(
        "SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
        "WHERE n.nspname = 'public' AND p.proname = 'immutable_unaccent'"
    )
    engine = create_async_engine(
        throwaway_dsn, isolation_level="AUTOCOMMIT", connect_args=LOCK_TIMEOUT
    )
    try:
        async with engine.connect() as c:
            # 14 tables of this revision plus public.tb_scope_token (added by the roles revision)
            assert await c.scalar(tables) == 15 and await c.scalar(views) == 2
            assert await c.scalar(func) == 1
        run_alembic(throwaway_dsn, "downgrade", "d7b3f9a2c6e4")
        async with engine.connect() as c:
            assert await c.scalar(tables) == 0 and await c.scalar(views) == 0
            assert await c.scalar(func) == 0
        run_alembic(throwaway_dsn, "upgrade", "head")
        async with engine.connect() as c:
            assert await c.scalar(tables) == 15 and await c.scalar(views) == 2
            assert await c.scalar(func) == 1
    finally:
        await engine.dispose()
