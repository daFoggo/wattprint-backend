import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import insert, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from app.database import Base
from app.models import InferenceRun, Series, WeatherHourly
from app.models.energy import device_estimate_table, reading_table

POLICY_PROCS = ("policy_compression", "policy_retention")
JOBS_SQL = text(
    "SELECT proc_name, hypertable_name FROM timescaledb_information.jobs "
    "WHERE hypertable_schema = 'public' AND hypertable_name IN ('tb_reading', 'tb_device_estimate') "
    "AND proc_name = ANY(:p) ORDER BY 1, 2"
)


async def _home(conn) -> int:
    return await conn.scalar(text("INSERT INTO public.tb_home (name) VALUES ('Home') RETURNING id"))


async def _device(conn, home_id) -> int:
    return await conn.scalar(
        text(
            "INSERT INTO public.tb_device (home_id, device_type_code, name, origin) "
            "VALUES (:h, 'ac', 'AC', 'manual') RETURNING id"
        ),
        {"h": home_id},
    )


async def _series(conn, home_id, kind="main", device_id=None, metric="power_w", **extra) -> int:
    cols = {
        "home_id": home_id,
        "kind": kind,
        "device_id": device_id,
        "metric": metric,
        "unit": "W",
        **extra,
    }
    names = ", ".join(cols)
    params = ", ".join(f":{k}" for k in cols)
    return await conn.scalar(
        text(f"INSERT INTO public.tb_series ({names}) VALUES ({params}) RETURNING series_id"), cols
    )


async def test_reading_is_hypertable_with_one_day_chunks(conn):
    for table in ("reading", "device_estimate"):
        interval = await conn.scalar(
            text(
                "SELECT d.time_interval FROM timescaledb_information.dimensions d "
                "WHERE d.hypertable_schema = 'public' AND d.hypertable_name = :t"
            ),
            {"t": table},
        )
        assert interval == timedelta(days=1), table


async def test_series_main_unique_per_home_metric(conn):
    home = await _home(conn)
    await _series(conn, home)
    with pytest.raises(IntegrityError):
        await _series(conn, home)


async def test_series_main_unique_allows_other_home_and_metric(conn):
    h1, h2 = await _home(conn), await _home(conn)
    await _series(conn, h1)
    await _series(conn, h2)
    await _series(conn, h1, metric="voltage_v")


async def test_series_kind_device_requires_device_id(conn):
    home = await _home(conn)
    for kind in ("plug", "device"):
        with pytest.raises(IntegrityError):
            async with conn.begin_nested():
                await _series(conn, home, kind=kind)


async def test_series_main_rejects_device_id(conn):
    home = await _home(conn)
    device = await _device(conn, home)
    with pytest.raises(IntegrityError):
        await _series(conn, home, kind="main", device_id=device)


async def test_series_kind_check(conn):
    home = await _home(conn)
    with pytest.raises(IntegrityError):
        await _series(conn, home, kind="bogus")


async def test_series_device_kinds_accept_device(conn):
    home = await _home(conn)
    device = await _device(conn, home)
    await _series(conn, home, kind="plug", device_id=device)
    await _series(conn, home, kind="device", device_id=device)


async def test_series_meter_channel_unique_when_both_set(conn):
    home = await _home(conn)
    meter = await conn.scalar(
        text("INSERT INTO public.tb_meter (serial) VALUES (:s) RETURNING id"),
        {"s": f"sn-{uuid.uuid4()}"},
    )
    await _series(conn, home, meter_id=meter, source_channel="ch1")
    with pytest.raises(IntegrityError):
        await _series(conn, home, metric="voltage_v", meter_id=meter, source_channel="ch1")


async def test_series_meter_channel_unique_ignores_nulls(conn):
    home = await _home(conn)
    meter = await conn.scalar(
        text("INSERT INTO public.tb_meter (serial) VALUES (:s) RETURNING id"),
        {"s": f"sn-{uuid.uuid4()}"},
    )
    # same meter, channel NULL: allowed (partial index only covers non-null pairs)
    await _series(conn, home, metric="power_w", meter_id=meter)
    await _series(conn, home, metric="voltage_v", meter_id=meter)
    # same non-null pair: rejected
    await _series(conn, home, metric="current_a", meter_id=meter, source_channel="ch1")
    with pytest.raises(IntegrityError):
        await _series(conn, home, metric="reactive_power_var", meter_id=meter, source_channel="ch1")


async def test_series_unknown_metric_rejected(conn):
    home = await _home(conn)
    with pytest.raises(IntegrityError):
        await _series(conn, home, metric="nope")


async def test_series_cascade_on_home_delete(conn):
    home = await _home(conn)
    sid = await _series(conn, home)
    await conn.execute(text("DELETE FROM public.tb_home WHERE id = :i"), {"i": home})
    assert (
        await conn.scalar(
            text("SELECT count(*) FROM public.tb_series WHERE series_id = :s"), {"s": sid}
        )
        == 0
    )


async def test_series_device_cascade_and_meter_set_null(conn):
    home = await _home(conn)
    device = await _device(conn, home)
    meter = await conn.scalar(
        text("INSERT INTO public.tb_meter (serial) VALUES (:s) RETURNING id"),
        {"s": f"sn-{uuid.uuid4()}"},
    )
    s_main = await _series(conn, home, meter_id=meter, source_channel="ch1")
    s_dev = await _series(conn, home, kind="device", device_id=device)
    await conn.execute(text("DELETE FROM public.tb_meter WHERE id = :i"), {"i": meter})
    assert (
        await conn.scalar(
            text("SELECT meter_id FROM public.tb_series WHERE series_id = :s"), {"s": s_main}
        )
        is None
    )
    await conn.execute(text("DELETE FROM public.tb_device WHERE id = :i"), {"i": device})
    assert (
        await conn.scalar(
            text("SELECT count(*) FROM public.tb_series WHERE series_id = :s"), {"s": s_dev}
        )
        == 0
    )


async def test_inference_run_status_check_and_defaults(conn):
    home = await _home(conn)
    now = datetime.now(UTC)
    sql = text(
        "INSERT INTO public.tb_inference_run (home_id, model_name, model_version, "
        "window_start, window_end, status) VALUES (:h, 'm', '1', :a, :b, :s) RETURNING run_id"
    )
    with pytest.raises(IntegrityError):
        async with conn.begin_nested():
            await conn.execute(sql, {"h": home, "a": now, "b": now, "s": "bogus"})
    rid = await conn.scalar(sql, {"h": home, "a": now, "b": now, "s": "ok"})
    assert rid is not None
    default = await conn.scalar(
        text(
            "INSERT INTO public.tb_inference_run (home_id, model_name, model_version, "
            "window_start, window_end) VALUES (:h, 'm', '1', :a, :b) RETURNING status"
        ),
        {"h": home, "a": now, "b": now},
    )
    assert default == "running"


async def test_compress_settings(conn):
    rows = (
        await conn.execute(
            text(
                "SELECT hypertable_name, attname, segmentby_column_index, orderby_column_index, "
                "orderby_asc FROM timescaledb_information.compression_settings "
                "WHERE hypertable_schema = 'public' AND "
                "hypertable_name IN ('reading','device_estimate')"
            )
        )
    ).all()
    for table in ("reading", "device_estimate"):
        mine = {r.attname: r for r in rows if r.hypertable_name == table}
        assert mine["series_id"].segmentby_column_index == 1
        assert mine["ts"].orderby_column_index == 1
        assert mine["ts"].orderby_asc is False
    enabled = await conn.scalar(
        text(
            "SELECT count(*) FROM timescaledb_information.hypertables "
            "WHERE hypertable_schema = 'public' AND compression_enabled"
        )
    )
    assert enabled == 2


async def test_on_conflict_do_nothing_on_compressed_chunk(conn):
    home = await _home(conn)
    sid = await _series(conn, home)
    ts = datetime(2020, 1, 1, 12, tzinfo=UTC)
    row = {"ts": ts, "series_id": sid, "value": 1.5, "quality": 0}
    await conn.execute(insert(reading_table).values(row))
    await conn.execute(
        text("SELECT compress_chunk(c, true) FROM show_chunks('public.tb_reading') c")
    )
    assert (
        await conn.scalar(
            text(
                "SELECT count(*) FROM timescaledb_information.chunks "
                "WHERE hypertable_schema = 'public' AND hypertable_name = 'tb_reading' "
                "AND is_compressed"
            )
        )
        == 1
    )
    dup = pg_insert(reading_table).values({**row, "value": 9.0}).on_conflict_do_nothing()
    await conn.execute(dup)
    assert (
        await conn.scalar(
            text("SELECT count(*) FROM public.tb_reading WHERE series_id = :s"), {"s": sid}
        )
        == 1
    )
    assert (
        await conn.scalar(
            text("SELECT value FROM public.tb_reading WHERE series_id = :s"), {"s": sid}
        )
        == 1.5
    )


async def test_device_estimate_insert(conn):
    home = await _home(conn)
    device = await _device(conn, home)
    sid = await _series(conn, home, kind="device", device_id=device)
    await conn.execute(
        insert(device_estimate_table).values(
            ts=datetime(2020, 1, 1, tzinfo=UTC), series_id=sid, value=2.0, run_id=None
        )
    )
    assert (
        await conn.scalar(
            text("SELECT count(*) FROM public.tb_device_estimate WHERE series_id = :s"), {"s": sid}
        )
        == 1
    )


async def test_set_policies_toggle(autocommit_conn):
    c = autocommit_conn
    p = {"p": list(POLICY_PROCS)}
    try:
        await c.execute(text("SELECT public.set_policies(true)"))
        await c.execute(text("SELECT public.set_policies(true)"))  # idempotent
        rows = (await c.execute(JOBS_SQL, p)).all()
        assert rows == [
            ("policy_compression", "device_estimate"),
            ("policy_compression", "reading"),
            ("policy_retention", "device_estimate"),
            ("policy_retention", "reading"),
        ]
        await c.execute(text("SELECT public.set_policies(false)"))
        await c.execute(text("SELECT public.set_policies(false)"))  # idempotent
        assert (await c.execute(JOBS_SQL, p)).all() == []
    finally:
        await c.execute(text("SELECT public.set_policies(true)"))
    assert len((await c.execute(JOBS_SQL, p)).all()) == 4


async def test_policy_intervals(autocommit_conn):
    rows = (
        await autocommit_conn.execute(
            text(
                "SELECT proc_name, config->>'compress_after' AS ca, config->>'drop_after' AS da "
                "FROM timescaledb_information.jobs WHERE hypertable_schema = 'public' "
                "AND hypertable_name = 'tb_reading' AND proc_name = ANY(:p)"
            ),
            {"p": list(POLICY_PROCS)},
        )
    ).all()
    by = {r.proc_name: r for r in rows}
    assert by["policy_compression"].ca == "2 days"
    assert by["policy_retention"].da == "400 days"


async def test_orm_round_trip(session):
    hid = await _home(await session.connection())
    now = datetime.now(UTC)
    s = Series(home_id=hid, kind="main", metric="power_w", unit="W")
    run = InferenceRun(
        home_id=hid, model_name="m", model_version="1", window_start=now, window_end=now
    )
    w = WeatherHourly(
        province_code="HN",
        ts=now.replace(minute=0, second=0, microsecond=0),
        temp_c=30.5,
        humidity_pct=70.0,
    )
    session.add_all([s, run, w])
    await session.flush()
    assert s.series_id is not None and run.run_id is not None
    await session.refresh(run)
    assert run.status == "running" and run.started_at is not None
    got = (await session.execute(select(WeatherHourly))).scalars().one()
    assert got.province_code == "HN" and got.temp_c == pytest.approx(30.5)


def test_metadata_resolves():
    names = {t.fullname for t in Base.metadata.sorted_tables}
    assert {
        "public.tb_series",
        "public.tb_inference_run",
        "public.tb_weather_hourly",
        "public.tb_reading",
        "public.tb_device_estimate",
    } <= names


async def test_energy_downgrade_upgrade(throwaway_dsn):
    from sqlalchemy.ext.asyncio import create_async_engine

    from tests.db.conftest import run_alembic

    q = text(
        "SELECT count(*) FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
    )
    fn = text(
        "SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
        "WHERE n.nspname = 'public' AND p.proname = 'set_policies'"
    )
    engine = create_async_engine(throwaway_dsn, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as c:
            assert await c.scalar(q) == 5
            assert await c.scalar(fn) == 1
        run_alembic(throwaway_dsn, "downgrade", "7a91e4d2b6c8")
        async with engine.connect() as c:
            assert await c.scalar(q) == 0
            assert await c.scalar(fn) == 0
        run_alembic(throwaway_dsn, "upgrade", "head")
        async with engine.connect() as c:
            assert await c.scalar(q) == 5
            assert len((await c.execute(JOBS_SQL, {"p": list(POLICY_PROCS)})).all()) == 4
    finally:
        await engine.dispose()


async def test_device_estimate_upsert_on_compressed_chunk_latest_run_wins(conn):
    home = await _home(conn)
    device = await _device(conn, home)
    sid = await _series(conn, home, kind="device", device_id=device)
    ts = datetime(2020, 1, 1, 12, tzinfo=UTC)
    now = datetime.now(UTC)
    runs = []
    for _ in range(2):
        runs.append(
            await conn.scalar(
                text(
                    "INSERT INTO public.tb_inference_run (home_id, model_name, model_version, "
                    "window_start, window_end) VALUES (:h, 'm', '1', :a, :a) RETURNING run_id"
                ),
                {"h": home, "a": now},
            )
        )
    await conn.execute(
        insert(device_estimate_table).values(ts=ts, series_id=sid, value=1.0, run_id=runs[0])
    )
    await conn.execute(
        text("SELECT compress_chunk(c, true) FROM show_chunks('public.tb_device_estimate') c")
    )
    stmt = pg_insert(device_estimate_table).values(ts=ts, series_id=sid, value=2.0, run_id=runs[1])
    await conn.execute(
        stmt.on_conflict_do_update(
            index_elements=["series_id", "ts"],
            set_={"value": stmt.excluded.value, "run_id": stmt.excluded.run_id},
        )
    )
    row = (
        await conn.execute(
            text("SELECT value, run_id FROM public.tb_device_estimate WHERE series_id = :s"),
            {"s": sid},
        )
    ).one()
    assert row.value == 2.0 and row.run_id == runs[1]


async def test_column_types_match_models(conn):
    rows = (
        await conn.execute(
            text(
                "SELECT table_name, column_name, data_type, character_maximum_length "
                "FROM information_schema.columns WHERE table_schema = 'public' "
                "AND table_name IN ('series')"
            )
        )
    ).all()
    got = {(r.table_name, r.column_name): (r.data_type, r.character_maximum_length) for r in rows}
    assert got[("series", "kind")] == ("character varying", 16)
    assert got[("series", "metric")] == ("character varying", 64)


async def test_hypertable_pk_names_and_meter_index(conn):
    names = set(
        (
            await conn.execute(
                text(
                    "SELECT conname FROM pg_constraint WHERE contype = 'p' AND conrelid IN "
                    "('public.tb_reading'::regclass, 'public.tb_device_estimate'::regclass)"
                )
            )
        ).scalars()
    )
    assert names == {"pk_reading", "pk_device_estimate"}
    cols = set(
        (
            await conn.execute(
                text(
                    "SELECT pg_get_indexdef(indexrelid) FROM pg_index "
                    "WHERE indrelid = 'public.tb_series'::regclass AND NOT indisunique"
                )
            )
        ).scalars()
    )
    assert any("(meter_id)" in d for d in cols)


async def test_set_policies_pins_search_path(conn):
    cfg = await conn.scalar(
        text(
            "SELECT proconfig::text FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
            "WHERE n.nspname = 'public' AND p.proname = 'set_policies'"
        )
    )
    assert cfg is not None and "search_path=public, pg_catalog" in cfg
