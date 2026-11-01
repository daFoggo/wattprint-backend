"""Role grants and the Copilot read-only views.

Every test runs on the superuser scratch connection inside a rolled-back transaction and
switches identity with SET LOCAL ROLE; no role password or login state is ever touched.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from tests.db.conftest import run_alembic
from tests.db.test_domain_tables import (
    mk_alert,
    mk_device,
    mk_home,
    mk_series,
    mk_suggestion,
)

APP = "wattprint_app"
INGEST = "wattprint_ingest"
COPILOT = "wattprint_copilot_ro"
ROLES = (APP, INGEST, COPILOT)
T0 = datetime(2026, 10, 1, 0, 0, tzinfo=UTC)  # 07:00 local: minutes 0-2 share hour and day

SCHEMAS = ("core", "catalog", "energy", "billing", "insight", "copilot", "knowledge", "ops")
COPILOT_VIEWS = (
    "home", "device", "series", "bill", "bill_item", "alert", "device_cycle", "suggestion",
    "forecast_snapshot", "reading_1m", "reading_1h", "reading_1d", "device_estimate_1m",
    "device_estimate_1h", "device_estimate_1d",
)
# rows each view shows for ONE home of the seed below
EXPECTED_ROWS = {
    "home": 1, "device": 1, "series": 2, "bill": 1, "bill_item": 2, "alert": 1,
    "device_cycle": 1, "suggestion": 1, "forecast_snapshot": 1,
    "reading_1m": 3, "reading_1h": 1, "reading_1d": 1,
    "device_estimate_1m": 3, "device_estimate_1h": 1, "device_estimate_1d": 1,
}


async def _seed_home(c, name: str) -> dict:
    home = await mk_home(c)
    await c.execute(text("UPDATE core.home SET name = :n WHERE id = :h"), {"n": name, "h": home})
    device = await mk_device(c, home)
    main = await mk_series(c, home)
    dev_series = await c.scalar(
        text(
            "INSERT INTO energy.series (home_id, kind, device_id, metric, unit) "
            "VALUES (:h, 'device', :d, 'power_w', 'W') RETURNING series_id"
        ),
        {"h": home, "d": device},
    )
    for i in range(3):
        ts = T0 + timedelta(minutes=i)
        await c.execute(
            text("INSERT INTO energy.reading (ts, series_id, value) VALUES (:t, :s, 100)"),
            {"t": ts, "s": main},
        )
        await c.execute(
            text("INSERT INTO energy.device_estimate (ts, series_id, value) VALUES (:t, :s, 50)"),
            {"t": ts, "s": dev_series},
        )
    version = await c.scalar(
        text("SELECT id FROM billing.tariff_version WHERE plan_code = 'vn_residential' LIMIT 1")
    )
    bill = await c.scalar(
        text(
            "INSERT INTO billing.bill (home_id, period_start, period_end, version_id, "
            "kwh_total, amount_before_vat, vat_amount, amount_total, coverage, status) "
            "VALUES (:h, '2026-10-01', '2026-10-31', :v, 10, 100, 8, 108, 1, 'open') "
            "RETURNING id"
        ),
        {"h": home, "v": version},
    )
    for label in ("a", "b"):
        await c.execute(
            text(
                "INSERT INTO billing.bill_item (bill_id, label, kwh, share, amount) "
                "VALUES (:b, :l, 5, 0.5, 54)"
            ),
            {"b": bill, "l": label},
        )
    await c.execute(
        text(
            "INSERT INTO insight.device_cycle (home_id, device_id, start_ts, end_ts, "
            "energy_wh, peak_w) VALUES (:h, :d, :s, :e, 1, 1)"
        ),
        {"h": home, "d": device, "s": T0, "e": T0 + timedelta(minutes=5)},
    )
    await c.execute(
        text(
            "INSERT INTO insight.forecast_snapshot (home_id, generated_at, horizon_date, kwh, "
            "amount, model_version) VALUES (:h, now(), '2026-10-31', 1, 1, 'm')"
        ),
        {"h": home},
    )
    return {
        "home": home, "device": device, "series": {main, dev_series}, "bill": bill,
        "alert": await mk_alert(c, home, device),
        "suggestion": await mk_suggestion(c, home, device),
    }


async def seed(c) -> tuple[dict, dict, dict]:
    """Two homes plus hostile rows: home_id = A but the device belongs to B."""
    a = await _seed_home(c, "A")
    b = await _seed_home(c, "B")
    hostile = {
        "alert": await mk_alert(c, a["home"], b["device"]),
        "suggestion": await mk_suggestion(c, a["home"], b["device"]),
    }
    await c.execute(
        text(
            "INSERT INTO insight.device_cycle (home_id, device_id, start_ts, end_ts, "
            "energy_wh, peak_w) VALUES (:h, :d, :s, :e, 999, 999)"
        ),
        {"h": a["home"], "d": b["device"], "s": T0 + timedelta(hours=3),
         "e": T0 + timedelta(hours=4)},
    )
    return a, b, hostile


async def as_role(c, role: str, home: uuid.UUID | str | None = None) -> None:
    if home is not None:
        await c.execute(text("SELECT set_config('app.home_id', :h, true)"), {"h": str(home)})
    await c.execute(text(f"SET LOCAL ROLE {role}"))


async def reset(c) -> None:
    await c.execute(text("RESET ROLE"))


async def view_count(c, view: str) -> int:
    return await c.scalar(text(f"SELECT count(*) FROM copilot_ro.{view}"))


async def view_ids(c, view: str, col: str = "id") -> set:
    return set((await c.execute(text(f"SELECT {col} FROM copilot_ro.{view}"))).scalars())


async def denied(c, sql: str, **params) -> None:
    """The statement must fail with 'permission denied' (SQLSTATE 42501), not 'does not exist'."""
    sp = await c.begin_nested()
    with pytest.raises(DBAPIError) as exc:
        await c.execute(text(sql), params)
    cause = exc.value.orig.__cause__
    assert cause.sqlstate == "42501", f"{sql!r}: {cause!r}"
    assert "permission denied" in str(cause)
    await sp.rollback()


# --- copilot: isolation ---


async def test_copilot_sees_only_own_home(conn):
    a, b, _ = await seed(conn)
    for home, other in ((a, b), (b, a)):
        await as_role(conn, COPILOT, home["home"])
        for view, n in EXPECTED_ROWS.items():
            assert await view_count(conn, view) == n, (view, "own home")
        assert await view_ids(conn, "home") == {home["home"]}
        assert await view_ids(conn, "device") == {home["device"]}
        assert await view_ids(conn, "series", "series_id") == home["series"]
        assert await view_ids(conn, "bill") == {home["bill"]}
        assert await view_ids(conn, "alert") == {home["alert"]}
        assert await view_ids(conn, "suggestion") == {home["suggestion"]}
        for res in ("1m", "1h", "1d"):
            for family in ("reading", "device_estimate"):
                got = await view_ids(conn, f"{family}_{res}", "series_id")
                assert got <= home["series"] and got.isdisjoint(other["series"])
        assert await view_ids(conn, "bill_item", "bill_id") == {home["bill"]}
        await reset(conn)


async def test_copilot_switching_setting_flips_result(conn):
    a, b, _ = await seed(conn)
    await as_role(conn, COPILOT, a["home"])
    assert await view_ids(conn, "home") == {a["home"]}
    await conn.execute(text("SELECT set_config('app.home_id', :h, true)"), {"h": str(b["home"])})
    assert await view_ids(conn, "home") == {b["home"]}


async def test_copilot_unset_home_returns_nothing(scratch_dsn):
    # NullPool: a brand new connection, so the setting was never defined in this session.
    engine = create_async_engine(scratch_dsn, poolclass=NullPool)
    try:
        async with engine.connect() as c:
            trans = await c.begin()
            await seed(c)
            await c.execute(text(f"SET LOCAL ROLE {COPILOT}"))
            assert await c.scalar(text("SELECT current_setting('app.home_id', true)")) is None
            for view in COPILOT_VIEWS:
                assert await view_count(c, view) == 0, (view, "unset")
            await c.execute(text("SELECT set_config('app.home_id', '', true)"))
            assert await c.scalar(text("SELECT current_setting('app.home_id', true)")) == ""
            for view in COPILOT_VIEWS:
                assert await view_count(c, view) == 0, (view, "empty")
            await trans.rollback()
    finally:
        await engine.dispose()


async def test_copilot_hostile_denormalized_rows_hidden(conn):
    a, b, hostile = await seed(conn)
    total = {
        "insight.alert": 3, "copilot.suggestion": 3, "insight.device_cycle": 3,
    }
    for table, n in total.items():  # the hostile rows really exist
        assert await conn.scalar(text(f"SELECT count(*) FROM {table}")) >= n
    for home in (a, b):
        await as_role(conn, COPILOT, home["home"])
        assert hostile["alert"] not in await view_ids(conn, "alert")
        assert hostile["suggestion"] not in await view_ids(conn, "suggestion")
        assert await view_count(conn, "device_cycle") == 1
        assert await conn.scalar(
            text("SELECT count(*) FROM copilot_ro.device_cycle WHERE energy_wh = 999")
        ) == 0
        await reset(conn)


async def test_copilot_can_override_home_setting_known_limitation(conn):
    """Characterisation, not an endorsement: app.home_id is a plain custom setting, so the role
    can set it itself. Isolation holds for statements the backend constructs; a raw-SQL tool
    must never hand the role free-form SQL. Revisit if the setting is ever protected."""
    a, b, _ = await seed(conn)
    await as_role(conn, COPILOT, a["home"])
    await conn.execute(text("SELECT set_config('app.home_id', :h, true)"), {"h": str(b["home"])})
    assert await view_ids(conn, "home") == {b["home"]}


# --- copilot: privileges ---


async def test_copilot_cannot_write(conn):
    a, _, _ = await seed(conn)
    await as_role(conn, COPILOT, a["home"])
    for sql in (
        "INSERT INTO copilot_ro.home (id, name) VALUES (gen_random_uuid(), 'x')",
        "UPDATE copilot_ro.home SET name = 'x'",
        "DELETE FROM copilot_ro.alert",
        "TRUNCATE knowledge.chunk",
        "UPDATE copilot_ro.bill SET status = 'x'",
        "DELETE FROM copilot_ro.device",
        "INSERT INTO knowledge.document (title, doc_type) VALUES ('t', 'guide')",
        "UPDATE knowledge.document SET title = 'x'",
        "DELETE FROM knowledge.chunk",
        "INSERT INTO catalog.metric (event_type, unit, aggregation) VALUES ('x', 'x', 'x')",
        "UPDATE catalog.device_type SET label_en = 'x'",
        "DELETE FROM catalog.metric",
        "UPDATE billing.tariff_plan SET name = 'x'",
        "DELETE FROM billing.tariff_tier",
    ):
        await denied(conn, sql)


COPILOT_DENIED_READS = (
    "energy.reading", "energy.series", "energy.device_estimate", "energy.reading_1m",
    "core.home", "core.home_member", "core.device", "public.users", "public.refresh_tokens",
    "billing.bill", "billing.bill_item", "copilot.message", "copilot.suggestion",
    "insight.alert", "insight.cohort_stat", "ops.ingest_batch",
)


@pytest.mark.parametrize("table", COPILOT_DENIED_READS)
async def test_copilot_cannot_read_base_tables(conn, table):
    a, _, _ = await seed(conn)
    await as_role(conn, COPILOT, a["home"])
    await denied(conn, f"SELECT * FROM {table}")


async def test_copilot_can_read_reference_data(conn):
    a, _, _ = await seed(conn)
    await as_role(conn, COPILOT, a["home"])
    for table in (
        "knowledge.document", "knowledge.chunk", "catalog.metric", "catalog.device_type",
        "billing.tariff_plan", "billing.tariff_version", "billing.tariff_tier",
    ):
        assert await conn.scalar(text(f"SELECT count(*) FROM {table}")) >= 0
    assert await conn.scalar(text("SELECT count(*) FROM billing.tariff_tier")) > 0


async def test_copilot_cannot_create_objects(conn):
    await as_role(conn, COPILOT)
    for schema in (*SCHEMAS, "copilot_ro", "public"):
        await denied(conn, f"CREATE TABLE {schema}.evil (x int)")
        await denied(conn, f"CREATE VIEW {schema}.evil AS SELECT 1")
        await denied(
            conn,
            f"CREATE FUNCTION {schema}.evil() RETURNS int LANGUAGE sql AS 'SELECT 1'",
        )


async def test_copilot_role_has_statement_timeout(conn):
    cfg = await conn.scalar(
        text("SELECT rolconfig FROM pg_roles WHERE rolname = :r"), {"r": COPILOT}
    )
    assert "statement_timeout=5s" in cfg


async def test_views_are_security_barrier(conn):
    rows = (
        await conn.execute(
            text(
                "SELECT c.relname, c.reloptions, pg_get_userbyid(c.relowner) "
                "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'copilot_ro'"
            )
        )
    ).all()
    assert {r[0] for r in rows} == set(COPILOT_VIEWS)
    for name, options, owner in rows:
        assert "security_barrier=true" in options, name
        assert owner not in ROLES, name  # the roles own nothing


async def test_no_privilege_for_public_on_new_objects(conn):
    public_grants = (
        await conn.execute(
            text(
                "SELECT c.relname FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace, "
                "LATERAL aclexplode(c.relacl) a "
                "WHERE n.nspname = 'copilot_ro' AND a.grantee = 0"
            )
        )
    ).all()
    assert public_grants == []
    schema_acl = await conn.scalar(
        text(
            "SELECT count(*) FROM pg_namespace n, LATERAL aclexplode(n.nspacl) a "
            "WHERE n.nspname = 'copilot_ro' AND a.grantee = 0"
        )
    )
    assert schema_acl == 0


# --- ingest ---


async def test_ingest_can_write_readings_and_ops(conn):
    a, _, _ = await seed(conn)
    main = (await conn.scalar(
        text("SELECT series_id FROM energy.series WHERE home_id = :h AND kind = 'main'"),
        {"h": a["home"]},
    ))
    dev = (await conn.scalar(
        text("SELECT series_id FROM energy.series WHERE home_id = :h AND kind = 'device'"),
        {"h": a["home"]},
    ))
    ts = T0 + timedelta(days=1)
    await as_role(conn, INGEST)
    await conn.execute(
        text("INSERT INTO energy.reading (ts, series_id, value) VALUES (:t, :s, 1) "
             "ON CONFLICT DO NOTHING"),
        {"t": ts, "s": main},
    )
    for v in (1, 2):
        await conn.execute(
            text(
                "INSERT INTO energy.device_estimate (ts, series_id, value) VALUES (:t, :s, :v) "
                "ON CONFLICT (series_id, ts) DO UPDATE SET value = EXCLUDED.value"
            ),
            {"t": ts, "s": dev, "v": v},
        )
    batch = await conn.scalar(
        text("INSERT INTO ops.ingest_batch (source) VALUES ('refit') RETURNING id")
    )
    await conn.execute(
        text("UPDATE ops.ingest_batch SET status = 'ok' WHERE id = :i"), {"i": batch}
    )
    for _ in range(2):
        await conn.execute(
            text(
                "INSERT INTO ops.ingest_checkpoint (source, series_id, last_ts) "
                "VALUES ('refit', :s, :t) "
                "ON CONFLICT (source, series_id) DO UPDATE SET last_ts = EXCLUDED.last_ts"
            ),
            {"s": main, "t": ts},
        )
    assert await conn.scalar(text("SELECT count(*) FROM core.meter")) >= 0
    assert await conn.scalar(text("SELECT count(*) FROM energy.series")) >= 2
    assert await conn.scalar(text("SELECT value FROM energy.device_estimate "
                                  "WHERE ts = :t AND series_id = :s"), {"t": ts, "s": dev}) == 2


async def test_ingest_cannot_delete_truncate_or_read_other_tables(conn):
    await seed(conn)
    await as_role(conn, INGEST)
    for sql in (
        "DELETE FROM energy.reading",
        "TRUNCATE energy.reading",
        "DELETE FROM energy.device_estimate",
        "TRUNCATE energy.device_estimate",
        "DELETE FROM ops.ingest_batch",
        "TRUNCATE ops.ingest_batch",
        "DELETE FROM ops.ingest_checkpoint",
        "UPDATE energy.reading SET value = 0",
        "UPDATE energy.series SET unit = 'x'",
        "INSERT INTO energy.series (home_id, kind, metric, unit) "
        "VALUES (gen_random_uuid(), 'main', 'power_w', 'W')",
        "SELECT * FROM core.home_member",
        "SELECT * FROM core.home",
        "SELECT * FROM public.users",
        "SELECT * FROM billing.bill",
        "SELECT * FROM copilot_ro.home",
        "SELECT * FROM energy.reading_1m",
        "SELECT * FROM catalog.metric",
        "UPDATE core.meter SET status = 'x'",
        "CREATE TABLE ops.evil (x int)",
        "CREATE TABLE energy.evil (x int)",
        "CREATE TABLE public.evil (x int)",
    ):
        await denied(conn, sql)


# --- app ---


async def test_app_dml_and_aggregate_reads(conn):
    a, _, _ = await seed(conn)
    await as_role(conn, APP)
    h = await conn.scalar(text("INSERT INTO core.home (name) VALUES ('N') RETURNING id"))
    await conn.execute(text("UPDATE core.home SET name = 'M' WHERE id = :h"), {"h": h})
    await conn.execute(text("DELETE FROM core.home WHERE id = :h"), {"h": h})
    sid = await conn.scalar(  # identity sequence usable
        text("INSERT INTO energy.series (home_id, kind, metric, unit) "
             "VALUES (:h, 'main', 'voltage_v', 'V') RETURNING series_id"),
        {"h": a["home"]},
    )
    assert sid
    for agg in ("reading_1m", "reading_1h", "reading_1d", "device_estimate_1m",
                "device_estimate_1h", "device_estimate_1d"):
        assert await conn.scalar(text(f"SELECT count(*) FROM energy.{agg}")) >= 1
    assert await conn.scalar(text("SELECT count(*) FROM ops.stale_series")) >= 0
    assert await conn.scalar(text("SELECT count(*) FROM catalog.metric")) > 0
    await conn.execute(text("SELECT count(*) FROM public.users"))
    await conn.execute(text("SELECT count(*) FROM public.refresh_tokens"))


async def test_app_cannot_touch_raw_hypertables_or_ops_writes(conn):
    await seed(conn)
    await as_role(conn, APP)
    for sql in (
        "INSERT INTO energy.reading (ts, series_id, value) VALUES (now(), 1, 1)",
        "SELECT * FROM energy.reading",
        "SELECT * FROM energy.device_estimate",
        "INSERT INTO energy.device_estimate (ts, series_id, value) VALUES (now(), 1, 1)",
        "INSERT INTO ops.ingest_batch (source) VALUES ('x')",
        "DELETE FROM ops.ingest_checkpoint",
        "INSERT INTO catalog.metric (event_type, unit, aggregation) VALUES ('x', 'x', 'x')",
        "SELECT * FROM copilot_ro.home",
        "CREATE TABLE core.evil (x int)",
        "TRUNCATE core.home",
    ):
        await denied(conn, sql)


# --- exhaustive privilege matrix ---

TABLE_PRIVS = ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER")
DML = {"SELECT", "INSERT", "UPDATE", "DELETE"}
AGGS = {f"energy.{f}_{r}" for f in ("reading", "device_estimate") for r in ("1m", "1h", "1d")}


def expected_app(rel: str) -> set[str]:
    schema = rel.split(".")[0]
    if schema in ("core", "billing", "insight", "copilot", "knowledge"):
        return DML
    if rel in ("energy.series", "energy.inference_run", "energy.weather_hourly",
               "public.users", "public.refresh_tokens"):
        return DML
    if schema in ("catalog", "ops") or rel in AGGS:
        return {"SELECT"}
    return set()


def expected_ingest(rel: str) -> set[str]:
    return {
        "core.meter": {"SELECT"},
        "energy.series": {"SELECT"},
        "energy.reading": {"SELECT", "INSERT"},
        "energy.device_estimate": {"SELECT", "INSERT", "UPDATE"},
        "ops.ingest_batch": {"SELECT", "INSERT", "UPDATE"},
        "ops.ingest_checkpoint": {"SELECT", "INSERT", "UPDATE"},
    }.get(rel, set())


COPILOT_TABLES = {
    "knowledge.document", "knowledge.chunk", "catalog.metric", "catalog.device_type",
    "billing.tariff_plan", "billing.tariff_version", "billing.tariff_tier",
}


def expected_copilot(rel: str) -> set[str]:
    return {"SELECT"} if rel.startswith("copilot_ro.") or rel in COPILOT_TABLES else set()


EXPECTED = {APP: expected_app, INGEST: expected_ingest, COPILOT: expected_copilot}
EXPECTED_USAGE = {
    APP: set(SCHEMAS),
    INGEST: {"core", "energy", "ops"},
    COPILOT: {"copilot_ro", "knowledge", "catalog", "billing"},
}
EXPECTED_SEQUENCES = {
    "energy.series_series_id_seq", "energy.inference_run_run_id_seq", "knowledge.chunk_id_seq",
}
ALL_SCHEMAS = (*SCHEMAS, "copilot_ro", "public")


async def relations(c) -> list[str]:
    rows = await c.execute(
        text(
            "SELECT n.nspname || '.' || c.relname FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = ANY(:s) AND c.relkind IN ('r', 'p', 'v', 'm', 'f')"
        ),
        {"s": list(ALL_SCHEMAS)},
    )
    return sorted(rows.scalars())


async def privilege_snapshot(c) -> dict:
    """What each role really holds: relations, schemas, sequences, grant options."""
    snap: dict = {}
    rels = await relations(c)
    seqs = (await c.execute(
        text(
            "SELECT n.nspname || '.' || c.relname FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = ANY(:s) AND c.relkind = 'S'"
        ),
        {"s": list(ALL_SCHEMAS)},
    )).scalars().all()
    existing = (await c.execute(
        text("SELECT nspname FROM pg_namespace WHERE nspname = ANY(:s)"), {"s": list(ALL_SCHEMAS)}
    )).scalars().all()
    for role in ROLES:
        held = {}
        for rel in rels:
            privs = set()
            for p in TABLE_PRIVS:
                has = "has_table_privilege"
                if await c.scalar(text(f"SELECT {has}(:r, :o, :p)"), {"r": role, "o": rel, "p": p}):
                    privs.add(p)
            for p in ("SELECT", "INSERT", "UPDATE", "REFERENCES"):  # column-level grants
                if await c.scalar(
                    text("SELECT has_any_column_privilege(:r, :o, :p)"),
                    {"r": role, "o": rel, "p": p},
                ):
                    privs.add(p)
            held[rel] = privs
        usage, create = set(), set()
        for schema in existing:
            if await c.scalar(text("SELECT has_schema_privilege(:r, :s, 'USAGE')"),
                              {"r": role, "s": schema}):
                usage.add(schema)
            if await c.scalar(text("SELECT has_schema_privilege(:r, :s, 'CREATE')"),
                              {"r": role, "s": schema}):
                create.add(schema)
        seq_held = set()
        for seq in seqs:
            for p in ("USAGE", "SELECT", "UPDATE"):
                if await c.scalar(text("SELECT has_sequence_privilege(:r, :o, :p)"),
                                  {"r": role, "o": seq, "p": p}):
                    seq_held.add(seq)
        grantable = await c.scalar(
            text(
                "SELECT (SELECT count(*) FROM pg_class c, LATERAL aclexplode(c.relacl) a "
                "WHERE a.grantee = (SELECT oid FROM pg_roles WHERE rolname = :r) "
                "AND a.is_grantable) + "
                "(SELECT count(*) FROM pg_namespace n, LATERAL aclexplode(n.nspacl) a "
                "WHERE a.grantee = (SELECT oid FROM pg_roles WHERE rolname = :r) "
                "AND a.is_grantable)"
            ),
            {"r": role},
        )
        snap[role] = {"rels": held, "usage": usage, "create": create, "seqs": seq_held,
                      "grantable": grantable}
    return snap


def _public_usage(role: str, snap: dict) -> set[str]:
    # USAGE on schema public comes from PUBLIC, not from a grant of this revision
    return snap[role]["usage"] - {"public"}


async def test_privilege_matrix_is_exactly_the_intended_grants(conn):
    snap = await privilege_snapshot(conn)
    for role in ROLES:
        got = snap[role]
        assert got["create"] == set(), (role, "CREATE on a schema")
        assert got["grantable"] == 0, (role, "WITH GRANT OPTION")
        assert _public_usage(role, snap) == EXPECTED_USAGE[role], role
        want = {rel: EXPECTED[role](rel) for rel in got["rels"]}
        diffs = {r: (got["rels"][r], want[r]) for r in want if got["rels"][r] != want[r]}
        assert diffs == {}, (role, diffs)
    assert snap[APP]["seqs"] == EXPECTED_SEQUENCES
    assert snap[INGEST]["seqs"] == set()
    assert snap[COPILOT]["seqs"] == set()


async def test_matrix_covers_all_domain_tables(conn):
    rels = await relations(conn)
    assert {"core.device_alert_rule", "copilot.savings_measure", "insight.device_cycle",
            "ops.stale_series", "energy.reading_1d"} <= set(rels)
    for rel in rels:  # a new table without a deliberate decision shows up here
        if rel.split(".")[0] in ("core", "billing", "insight", "copilot", "knowledge"):
            assert expected_app(rel) == DML


# --- migration round trip ---


async def test_revision_downgrade_removes_grants_and_upgrade_restores_them(throwaway_dsn):
    engine = create_async_engine(throwaway_dsn, poolclass=NullPool)

    async def snapshot():
        async with engine.connect() as c:
            return await privilege_snapshot(c), await c.scalar(
                text("SELECT count(*) FROM pg_namespace WHERE nspname = 'copilot_ro'")
            )

    try:
        before, schema_before = await snapshot()
        assert schema_before == 1 and before[COPILOT]["usage"] - {"public"}
        run_alembic(throwaway_dsn, "downgrade", "-1")
        after, schema_after = await snapshot()
        assert schema_after == 0
        for role in ROLES:
            assert after[role]["usage"] - {"public"} == set(), role
            assert after[role]["seqs"] == set(), role
            assert after[role]["grantable"] == 0
            assert all(p == set() for p in after[role]["rels"].values()), (
                role, {r: p for r, p in after[role]["rels"].items() if p},
            )
        async with engine.connect() as c:  # roles themselves are untouched
            n = await c.scalar(
                text("SELECT count(*) FROM pg_roles WHERE rolname = ANY(:r)"), {"r": list(ROLES)}
            )
            assert n == 3
        run_alembic(throwaway_dsn, "upgrade", "head")
        again, _ = await snapshot()
        for role in ROLES:
            assert again[role]["usage"] == before[role]["usage"]
            assert again[role]["seqs"] == before[role]["seqs"]
            assert {r: p for r, p in again[role]["rels"].items() if p} == {
                r: p for r, p in before[role]["rels"].items() if p
            }
    finally:
        await engine.dispose()


async def test_reading_view_pushes_series_filter_into_aggregate(conn):
    a, _, _ = await seed(conn)
    await as_role(conn, COPILOT, a["home"])
    plan = "\n".join((await conn.execute(
        text("EXPLAIN SELECT count(*) FROM copilot_ro.reading_1m "
             "WHERE bucket >= :a AND bucket < :b"),
        {"a": T0, "b": T0 + timedelta(days=1)},
    )).scalars())
    # without the pushdown the aggregate is computed for every home and filtered afterwards
    assert "series_id = ANY" in plan, plan
