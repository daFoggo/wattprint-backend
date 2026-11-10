import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.services.aggregates import backfill_aggregates as backfill
from tests.db.conftest import _create_migrated_db, run_alembic

RAW_JOBS = text(
    "SELECT proc_name, hypertable_name FROM timescaledb_information.jobs "
    "WHERE hypertable_schema = 'public' AND hypertable_name IN ('reading', 'device_estimate') "
    "AND proc_name IN ('policy_compression', 'policy_retention') ORDER BY 1, 2"
)


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=UTC)


@pytest.fixture(scope="module")
async def agg_conn():
    """Private migrated database with background policies off, so tests control refreshes."""
    dsn, drop = await _create_migrated_db()
    engine = create_async_engine(dsn, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as c:
            await c.execute(text("SELECT public.set_policies(false)"))
            yield c
    finally:
        await engine.dispose()
        await drop()


@asynccontextmanager
async def series(c, table="reading"):
    """A committed home + main series; raw rows, series and home are removed afterwards."""
    home = await c.scalar(text("INSERT INTO public.tb_home (name) VALUES ('Agg') RETURNING id"))
    sid = await c.scalar(
        text(
            "INSERT INTO public.tb_series (home_id, kind, metric, unit) "
            "VALUES (:h, 'main', 'power_w', 'W') RETURNING series_id"
        ),
        {"h": home},
    )
    try:
        yield sid
    finally:
        for t in ("reading", "device_estimate"):
            await c.execute(text(f"DELETE FROM public.{t} WHERE series_id = :s"), {"s": sid})
        await c.execute(text("DELETE FROM public.tb_series WHERE series_id = :s"), {"s": sid})
        await c.execute(text("DELETE FROM public.tb_home WHERE id = :i"), {"i": home})


async def put(c, sid, ts, value, quality=0):
    await c.execute(
        text("INSERT INTO public.tb_reading (ts, series_id, value, quality) VALUES (:t,:s,:v,:q)"),
        {"t": ts, "s": sid, "v": value, "q": quality},
    )


async def put_est(c, sid, ts, value):
    await c.execute(
        text("INSERT INTO public.tb_device_estimate (ts, series_id, value) VALUES (:t,:s,:v)"),
        {"t": ts, "s": sid, "v": value},
    )


async def rows(c, view, sid):
    res = await c.execute(
        text(f"SELECT * FROM public.{view} WHERE series_id = :s ORDER BY bucket"), {"s": sid}
    )
    return res.mappings().all()


async def test_1m_energy_rule(agg_conn):
    c = agg_conn
    t0 = utc(2020, 1, 1, 3, 0)
    async with series(c) as sid:
        for i, v in enumerate((100, 200, 300)):
            await put(c, sid, t0 + timedelta(seconds=10 * i), v)
        await backfill(c, t0 - timedelta(days=1), t0 + timedelta(days=1))
        (r,) = await rows(c, "reading_1m", sid)
    assert r["bucket"] == t0
    assert r["avg_w"] == pytest.approx(200)
    assert (r["min_w"], r["max_w"], r["last_w"], r["n"]) == (100, 300, 300, 3)
    assert r["energy_wh"] == pytest.approx(200 * 60 / 3600)


async def test_1h_avg_is_sample_weighted(agg_conn):
    c = agg_conn
    t0 = utc(2020, 1, 2, 3, 0)
    async with series(c) as sid:
        await put(c, sid, t0, 100)
        for i, v in enumerate((200, 400, 300)):
            await put(c, sid, t0 + timedelta(minutes=1, seconds=10 * i), v)
        await backfill(c, t0 - timedelta(days=1), t0 + timedelta(days=1))
        (r,) = await rows(c, "reading_1h", sid)
        (d,) = await rows(c, "reading_1d", sid)
    assert (d["avg_w"], d["min_w"], d["max_w"], d["last_w"]) == (
        pytest.approx(250),
        100,
        400,
        300,
    )
    assert (d["n"], d["covered_minutes"]) == (4, 2)
    assert r["avg_w"] == pytest.approx((100 * 1 + 300 * 3) / 4)  # not the mean of means (200)
    assert (r["min_w"], r["max_w"], r["last_w"], r["n"], r["covered_minutes"]) == (
        100,
        400,
        300,
        4,
        2,
    )
    assert r["energy_wh"] == pytest.approx((100 + 300) * 60 / 3600)


async def test_gap_leaves_missing_minutes(agg_conn):
    c = agg_conn
    t0 = utc(2020, 1, 3, 3, 0)
    async with series(c) as sid:
        await put(c, sid, t0, 600)
        await put(c, sid, t0 + timedelta(minutes=10), 1200)
        await backfill(c, t0 - timedelta(days=1), t0 + timedelta(days=1))
        (h,) = await rows(c, "reading_1h", sid)
        (d,) = await rows(c, "reading_1d", sid)
        m = await rows(c, "reading_1m", sid)
    assert len(m) == 2
    assert h["covered_minutes"] == 2
    assert h["energy_wh"] == pytest.approx((600 + 1200) * 60 / 3600)
    assert d["covered_minutes"] == 2
    assert d["energy_wh"] == pytest.approx(h["energy_wh"])


async def test_daily_bucket_cut_at_17_utc(agg_conn):
    c = agg_conn
    async with series(c) as sid:
        await put(c, sid, utc(2013, 10, 9, 16, 59, 59), 100)
        await put(c, sid, utc(2013, 10, 9, 17, 0, 0), 200)
        await backfill(c, utc(2013, 10, 7), utc(2013, 10, 12))
        d = await rows(c, "reading_1d", sid)
    assert [r["bucket"] for r in d] == [utc(2013, 10, 8, 17), utc(2013, 10, 9, 17)]
    assert [r["n"] for r in d] == [1, 1]


async def test_quality_flagged_rows_excluded_from_reading_aggregates(agg_conn):
    c = agg_conn
    t0 = utc(2020, 1, 4, 3, 0)
    async with series(c) as sid:
        await put(c, sid, t0, 100)
        await put(c, sid, t0 + timedelta(seconds=10), 9999, quality=1)
        await put(c, sid, t0 + timedelta(seconds=20), 300, quality=2)  # other bit: kept
        await put(c, sid, t0 + timedelta(seconds=30), 8888, quality=3)  # bit 0 set: dropped
        await backfill(c, t0 - timedelta(days=1), t0 + timedelta(days=1))
        (m,) = await rows(c, "reading_1m", sid)
        (h,) = await rows(c, "reading_1h", sid)
    assert (m["n"], m["max_w"], m["avg_w"]) == (2, 300, pytest.approx(200))
    assert h["n"] == 2


async def test_device_estimate_not_filtered_by_quality(agg_conn):
    c = agg_conn
    t0 = utc(2020, 1, 5, 3, 0)
    async with series(c) as sid:
        for i, v in enumerate((100, 200, 300)):
            await put_est(c, sid, t0 + timedelta(seconds=10 * i), v)
        inserted = await c.scalar(
            text("SELECT count(*) FROM public.tb_device_estimate WHERE series_id = :s"), {"s": sid}
        )
        await backfill(c, t0 - timedelta(days=1), t0 + timedelta(days=1))
        (m,) = await rows(c, "device_estimate_1m", sid)
        (h,) = await rows(c, "device_estimate_1h", sid)
        (d,) = await rows(c, "device_estimate_1d", sid)
    assert inserted == 3
    assert m["n"] == inserted and m["avg_w"] == pytest.approx(200)
    assert m["energy_wh"] == pytest.approx(200 * 60 / 3600)
    assert (h["n"], h["covered_minutes"]) == (3, 1)
    assert (d["n"], d["covered_minutes"]) == (3, 1)


async def test_realtime_aggregation_on(agg_conn):
    c = agg_conn
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    async with series(c) as sid:
        await backfill(c, now - timedelta(hours=2), now)
        await put(c, sid, now + timedelta(seconds=30), 500)
        (r,) = await rows(c, "reading_1m", sid)
        mat_only = await c.scalar(
            text(
                "SELECT bool_and(materialized_only) "
                "FROM timescaledb_information.continuous_aggregates "
                "WHERE view_schema = 'public'"
            )
        )
    assert r["bucket"] == now and r["avg_w"] == pytest.approx(500)
    assert mat_only is False


async def test_late_row_needs_backfill(agg_conn):
    c = agg_conn
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    old = now - timedelta(days=10)
    async with series(c) as sid:
        # The watermark only advances as far as the newest raw row, so write a recent row first,
        # then refresh a window far newer than the old row to move the watermark past it.
        await put(c, sid, now - timedelta(minutes=1), 100)
        await backfill(c, now - timedelta(days=1), now)
        await put(c, sid, old, 700)
        buckets = [r["bucket"] for r in await rows(c, "reading_1m", sid)]
        assert buckets == [now - timedelta(minutes=1)]
        await backfill(c, old - timedelta(days=1), old + timedelta(days=1))
        r = (await rows(c, "reading_1m", sid))[0]
        assert r["bucket"] == old and r["avg_w"] == pytest.approx(700)
        h = (await rows(c, "reading_1h", sid))[0]
        assert h["bucket"] == old.replace(minute=0) and h["covered_minutes"] == 1


async def test_backfill_to_now_keeps_current_buckets_realtime(agg_conn):
    c = agg_conn
    # Stay clear of an hour (hence day) boundary so both rows fall in the same open buckets.
    to_boundary = 3600 - (datetime.now(UTC).timestamp() % 3600)
    if to_boundary < 30:
        await asyncio.sleep(to_boundary + 1)
    now = datetime.now(UTC)
    async with series(c) as sid:
        await put(c, sid, now, 100)
        await backfill(c, now - timedelta(days=2), now)
        await put(c, sid, now + timedelta(seconds=5), 300)
        h = await rows(c, "reading_1h", sid)
        d = await rows(c, "reading_1d", sid)
        # Both rows are served live from the open current buckets...
        hour = now.replace(minute=0, second=0, microsecond=0)
        assert [(r["bucket"], r["n"]) for r in h] == [(hour, 2)]
        assert [r["n"] for r in d] == [2]
        # ...and no current bucket was materialized (nothing frozen, watermark not past now).
        for view in ("reading_1h", "reading_1d"):
            mat = await c.scalar(
                text(
                    "SELECT format('%I.%I', materialization_hypertable_schema, "
                    "materialization_hypertable_name) FROM "
                    "timescaledb_information.continuous_aggregates WHERE view_name = :v"
                ),
                {"v": view},
            )
            assert (
                await c.scalar(text(f"SELECT count(*) FROM {mat} WHERE series_id = :s"), {"s": sid})
                == 0
            )


async def test_backfill_rejects_naive_datetimes_and_transactional_connection(agg_conn, conn):
    with pytest.raises(ValueError):
        await backfill(agg_conn, datetime(2020, 1, 1), datetime(2020, 1, 2))
    with pytest.raises(RuntimeError):
        await backfill(conn, utc(2020, 1, 1), utc(2020, 1, 2))


async def test_set_policies_adds_aggregate_policies_and_removes_them(conn):
    refresh = text(
        "SELECT config->>'start_offset', config->>'end_offset', schedule_interval::text, "
        "count(*) FROM timescaledb_information.jobs "
        "WHERE proc_name = 'policy_refresh_continuous_aggregate' GROUP BY 1, 2, 3 ORDER BY 1"
    )
    retention = text(
        "SELECT count(*) FROM timescaledb_information.jobs WHERE proc_name = 'policy_retention'"
    )
    await conn.execute(text("SELECT public.set_policies(true)"))
    await conn.execute(text("SELECT public.set_policies(true)"))  # idempotent
    got = {tuple(r[:3]): r[3] for r in (await conn.execute(refresh)).all()}
    assert got == {
        ("7 days", "00:01:00", "00:01:00"): 2,
        ("30 days", "01:00:00", "01:00:00"): 2,
        ("60 days", "01:00:00", "01:00:00"): 2,
    }
    assert await conn.scalar(retention) == 4  # 2 raw + 2 one-minute aggregates
    await conn.execute(text("SELECT public.set_policies(false)"))
    await conn.execute(text("SELECT public.set_policies(false)"))
    assert (await conn.execute(refresh)).all() == []
    assert await conn.scalar(retention) == 0
    await conn.execute(text("SELECT public.set_policies(true)"))
    assert await conn.scalar(retention) == 4


async def test_search_path_pin_survives_replace(conn):
    cfg = await conn.scalar(
        text(
            "SELECT proconfig::text FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
            "WHERE n.nspname = 'public' AND p.proname = 'set_policies'"
        )
    )
    assert cfg is not None and "search_path=public, pg_catalog" in cfg


async def test_aggregates_downgrade_upgrade(throwaway_dsn):
    views = text(
        "SELECT count(*) FROM timescaledb_information.continuous_aggregates "
        "WHERE view_schema = 'public'"
    )
    engine = create_async_engine(throwaway_dsn, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as c:
            assert await c.scalar(views) == 6
        run_alembic(throwaway_dsn, "downgrade", "b9d2e6f0a384")
        async with engine.connect() as c:
            assert await c.scalar(views) == 0
            cfg, body = (
                await c.execute(
                    text(
                        "SELECT proconfig::text, prosrc FROM pg_proc p "
                        "JOIN pg_namespace n ON n.oid = p.pronamespace "
                        "WHERE n.nspname = 'public' AND p.proname = 'set_policies'"
                    )
                )
            ).one()
            assert "search_path" in cfg
            assert "continuous_aggregate" not in body and "_1m" not in body
            raw = (await c.execute(RAW_JOBS)).all()
            assert [tuple(r) for r in raw] == [
                ("policy_compression", "device_estimate"),
                ("policy_compression", "reading"),
                ("policy_retention", "device_estimate"),
                ("policy_retention", "reading"),
            ]
            await c.execute(text("SELECT public.set_policies(true)"))
            assert len((await c.execute(RAW_JOBS)).all()) == 4
        run_alembic(throwaway_dsn, "upgrade", "head")
        async with engine.connect() as c:
            assert await c.scalar(views) == 6
            n = await c.scalar(
                text(
                    "SELECT count(*) FROM timescaledb_information.jobs "
                    "WHERE proc_name = 'policy_refresh_continuous_aggregate'"
                )
            )
            assert n == 6
    finally:
        await engine.dispose()
