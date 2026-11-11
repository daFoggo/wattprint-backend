"""Compression of the 1 m continuous aggregates (migration f3a9c1e5b7d2) and its policies."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.modules.energy.services.aggregates import backfill_aggregates
from app.modules.energy.services.meter import meter_series
from tests.db.conftest import _create_migrated_db, run_alembic

D = [datetime(2026, 2, d, tzinfo=UTC) for d in range(1, 6)]
CAGGS = ("reading_1m", "device_estimate_1m")
VIEWS = (
    "reading_1m",
    "reading_1h",
    "reading_1d",
    "device_estimate_1m",
    "device_estimate_1h",
    "device_estimate_1d",
)
REFRESH = (
    "CALL refresh_continuous_aggregate(CAST(:v AS regclass), CAST(:a AS timestamptz), "
    "CAST(:b AS timestamptz), force => true)"
)
MAT_JOIN = (
    "JOIN timescaledb_information.continuous_aggregates ca "
    "ON ca.materialization_hypertable_schema = {t}.hypertable_schema "
    "AND ca.materialization_hypertable_name = {t}.hypertable_name"
)


async def seed(c, days=3):
    """One series with raw readings and estimates, 2 h per day at 10 s, fully backfilled."""
    home = await c.scalar(text("INSERT INTO public.tb_home (name) VALUES ('C') RETURNING id"))
    sid = await c.scalar(
        text(
            "INSERT INTO public.tb_series (home_id, kind, metric, unit) "
            "VALUES (:h, 'main', 'power_w', 'W') RETURNING series_id"
        ),
        {"h": home},
    )
    for day in D[:days]:
        window = {"s": sid, "a": day + timedelta(hours=2), "b": day + timedelta(hours=4)}
        await c.execute(
            text(
                "INSERT INTO public.tb_reading (ts, series_id, value) "
                "SELECT g, :s, 100 + (extract(epoch FROM g)::int / 10) % 50 "
                "FROM generate_series(CAST(:a AS timestamptz), CAST(:b AS timestamptz), "
                "interval '10 seconds') g"
            ),
            window,
        )
        await c.execute(
            text(
                "INSERT INTO public.tb_device_estimate (ts, series_id, value) "
                "SELECT g, :s, 50 FROM generate_series(CAST(:a AS timestamptz), "
                "CAST(:b AS timestamptz), interval '10 seconds') g"
            ),
            window,
        )
    await backfill_aggregates(c, D[0], D[4])
    return home, sid


async def snapshot(c, sid):
    out = {}
    for v in VIEWS:
        res = await c.execute(
            text(f"SELECT * FROM public.{v} WHERE series_id = :s ORDER BY bucket"), {"s": sid}
        )
        out[v] = [tuple(r) for r in res]
    return out


async def mat_chunks(c, view):
    res = await c.execute(
        text(
            "SELECT format('%I.%I', ch.chunk_schema, ch.chunk_name) "
            "FROM timescaledb_information.chunks ch "
            + MAT_JOIN.format(t="ch")
            + " WHERE ca.view_name = :v AND NOT ch.is_compressed ORDER BY ch.range_start"
        ),
        {"v": view},
    )
    return [r[0] for r in res]


async def compress_1m(c):
    n = 0
    for view in CAGGS:
        for ch in await mat_chunks(c, view):
            await c.execute(text("SELECT compress_chunk(CAST(:c AS regclass))"), {"c": ch})
            n += 1
    return n


async def compressed_count(c, view):
    return await c.scalar(
        text(
            "SELECT count(*) FROM timescaledb_information.chunks ch "
            + MAT_JOIN.format(t="ch")
            + " WHERE ca.view_name = :v AND ch.is_compressed"
        ),
        {"v": view},
    )


async def compression_settings(c, view):
    """(segmentby, orderby) of the materialization hypertable, (None, None) when not enabled."""
    row = (
        await c.execute(
            text(
                "SELECT s.segmentby, s.orderby "
                "FROM timescaledb_information.hypertable_compression_settings s "
                "JOIN timescaledb_information.continuous_aggregates ca "
                "ON s.hypertable::text = format('%I.%I', ca.materialization_hypertable_schema, "
                "ca.materialization_hypertable_name) WHERE ca.view_name = :v"
            ),
            {"v": view},
        )
    ).one()
    return row.segmentby, row.orderby


async def compression_enabled(c, view):
    return await compression_settings(c, view) != (None, None)


@pytest.fixture
async def cc():
    dsn, drop = await _create_migrated_db()
    engine = create_async_engine(dsn, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as c:
            await c.execute(text("SELECT public.set_policies(false)"))
            yield c
    finally:
        await engine.dispose()
        await drop()


async def test_compression_is_enabled_on_the_1m_caggs_only(cc):
    for view in CAGGS:
        assert await compression_settings(cc, view) == ("series_id", "bucket DESC"), view
        # real-time aggregation stays on next to compression
        assert (
            await cc.scalar(
                text(
                    "SELECT materialized_only FROM timescaledb_information.continuous_aggregates "
                    "WHERE view_name = :v"
                ),
                {"v": view},
            )
            is False
        )
    for view in ("reading_1h", "reading_1d", "device_estimate_1h", "device_estimate_1d"):
        assert await compression_enabled(cc, view) is False, view


async def test_compressing_1m_chunks_keeps_every_view_identical(cc):
    _, sid = await seed(cc)
    before = await snapshot(cc, sid)
    assert len(before["reading_1m"]) > 300 and len(before["device_estimate_1m"]) > 300
    assert await compress_1m(cc) >= 2
    assert await compressed_count(cc, "reading_1m") >= 1
    assert await snapshot(cc, sid) == before  # real-time views read compressed chunks correctly


async def test_refresh_over_compressed_range_applies_late_data(cc):
    _, sid = await seed(cc)
    await compress_1m(cc)
    day = D[1]
    # a late sample in an existing minute and one in a brand-new minute of a compressed range
    for ts, v in ((day + timedelta(hours=2, seconds=5), 1000), (day + timedelta(hours=7), 600)):
        await cc.execute(
            text("INSERT INTO public.tb_reading (ts, series_id, value) VALUES (:t, :s, :v)"),
            {"t": ts, "s": sid, "v": v},
        )
    await backfill_aggregates(cc, D[0], D[4])
    window = {"s": sid, "a": day, "b": day + timedelta(days=1)}
    raw = {
        r.minute: r
        for r in await cc.execute(
            text(
                "SELECT date_trunc('minute', ts) AS minute, avg(value) AS avg_w, count(*) AS n "
                "FROM public.tb_reading WHERE series_id = :s AND ts >= :a AND ts < :b GROUP BY 1"
            ),
            window,
        )
    }
    view = {
        r.bucket: r
        for r in await cc.execute(
            text(
                "SELECT * FROM public.reading_1m WHERE series_id = :s "
                "AND bucket >= :a AND bucket < :b"
            ),
            window,
        )
    }
    assert set(raw) == set(view)
    for minute, r in raw.items():
        assert view[minute].n == r.n
        assert view[minute].avg_w == pytest.approx(float(r.avg_w))
        assert view[minute].energy_wh == pytest.approx(float(r.avg_w) * 60 / 3600)
    assert day + timedelta(hours=7) in view  # the new minute exists
    # 1 h and 1 d follow from the (compressed) 1 m
    span = {"s": sid, "a": day - timedelta(hours=7), "b": day + timedelta(hours=17)}  # local day
    want = await cc.scalar(
        text(
            "SELECT sum(energy_wh) FROM public.reading_1m WHERE series_id = :s "
            "AND bucket >= :a AND bucket < :b"
        ),
        span,
    )
    for res in ("1h", "1d"):
        got = await cc.scalar(
            text(
                f"SELECT sum(energy_wh) FROM public.reading_{res} WHERE series_id = :s "
                "AND bucket >= :a AND bucket < :b"
            ),
            span,
        )
        assert got == pytest.approx(want), res


async def test_1h_and_1d_recomputed_from_compressed_1m_match(cc):
    _, sid = await seed(cc)
    before = await snapshot(cc, sid)
    await compress_1m(cc)
    for view in ("reading_1h", "reading_1d", "device_estimate_1h", "device_estimate_1d"):
        await cc.execute(
            text(REFRESH), {"v": f"public.{view}", "a": D[0] - timedelta(days=1), "b": D[4]}
        )
    after = await snapshot(cc, sid)
    for view in VIEWS:
        assert len(after[view]) == len(before[view]), view
        for a, b in zip(after[view], before[view], strict=True):
            assert a[:2] == b[:2]  # bucket, series
            assert a[2:] == pytest.approx(b[2:], rel=1e-9), view


async def read_series(conn, home, since, until, now):
    async with AsyncSession(bind=conn, expire_on_commit=False) as s:
        return await meter_series(s, home, since, until, max_points=60, now=now)


async def test_meter_service_reads_compressed_1m(cc):
    home, _ = await seed(cc)
    since, until = D[1] + timedelta(hours=1), D[1] + timedelta(hours=6)
    before = await read_series(cc, home, since, until, D[4])
    assert len(before) == 25  # data only 02:00-04:00, 5 minute steps
    await compress_1m(cc)
    after = await read_series(cc, home, since, until, D[4])
    assert [p.ts for p in after] == [p.ts for p in before]
    for a, b in zip(after, before, strict=True):  # re-bucketed sums may differ in the last digit
        assert (a.avg_w, a.min_w, a.max_w, a.energy_wh) == pytest.approx(
            (b.avg_w, b.min_w, b.max_w, b.energy_wh), rel=1e-12
        )


async def jobs(c):
    res = await c.execute(
        text(
            "SELECT hypertable_name, config->>'compress_after' AS after "
            "FROM timescaledb_information.jobs WHERE proc_name = 'policy_compression' "
            "ORDER BY hypertable_name"
        )
    )
    return [tuple(r) for r in res]


async def test_set_policies_adds_and_removes_1m_compression_policies(cc):
    await cc.execute(text("SELECT public.set_policies(true)"))
    await cc.execute(text("SELECT public.set_policies(true)"))  # idempotent
    assert await jobs(cc) == [
        ("device_estimate_1m", "14 days"),
        ("reading_1m", "14 days"),
        ("tb_device_estimate", "2 days"),
        ("tb_reading", "2 days"),
    ]
    # compress_after of a cagg must exceed the 1 m refresh start_offset (7 days)
    start = await cc.scalar(
        text(
            "SELECT config->>'start_offset' FROM timescaledb_information.jobs WHERE proc_name = "
            "'policy_refresh_continuous_aggregate' AND hypertable_name = 'reading_1m'"
        )
    )
    assert start == "7 days"
    await cc.execute(text("SELECT public.set_policies(false)"))
    await cc.execute(text("SELECT public.set_policies(false)"))
    assert await jobs(cc) == []
    await cc.execute(text("SELECT public.set_policies(true)"))
    assert len(await jobs(cc)) == 4
    await cc.execute(text("SELECT public.set_policies(false)"))


async def test_compression_policy_job_compresses_old_1m_chunks(cc):
    _, sid = await seed(cc)
    before = await snapshot(cc, sid)
    # create and pause the jobs in one transaction, then run the 1 m compression job by hand
    await cc.execute(
        text(
            "DO $$ BEGIN PERFORM public.set_policies(true); "
            "PERFORM alter_job(job_id, scheduled => false) "
            "FROM timescaledb_information.jobs WHERE hypertable_name IS NOT NULL; END $$"
        )
    )
    job = await cc.scalar(
        text(
            "SELECT job_id FROM timescaledb_information.jobs "
            "WHERE proc_name = 'policy_compression' AND hypertable_name = 'reading_1m'"
        )
    )
    await cc.execute(text("CALL run_job(:j)"), {"j": job})
    assert await compressed_count(cc, "reading_1m") >= 1  # the data is from 2026-02, > 14 days old
    assert await snapshot(cc, sid) == before
    await cc.execute(text("SELECT public.set_policies(false)"))


async def test_downgrade_removes_compression_and_upgrade_restores_it(throwaway_dsn):
    engine = create_async_engine(throwaway_dsn, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as c:
            await c.execute(text("SELECT public.set_policies(false)"))
            _, sid = await seed(c)
            assert await compress_1m(c) >= 2
            await c.execute(text("SELECT public.set_policies(true)"))
            before = await snapshot(c, sid)
        run_alembic(throwaway_dsn, "downgrade", "4d7b1e9a3c52")
        async with engine.connect() as c:
            assert [g[0] for g in await jobs(c)] == ["tb_device_estimate", "tb_reading"]
            for view in CAGGS:
                assert await compressed_count(c, view) == 0
                assert await compression_enabled(c, view) is False
            assert await snapshot(c, sid) == before  # data survives the decompression
            await c.execute(text("SELECT public.set_policies(true)"))
            assert [g[0] for g in await jobs(c)] == ["tb_device_estimate", "tb_reading"]
        run_alembic(throwaway_dsn, "upgrade", "head")
        async with engine.connect() as c:
            await c.execute(text("SELECT public.set_policies(true)"))
            assert len(await jobs(c)) == 4
            assert await compress_1m(c) >= 1
            assert await snapshot(c, sid) == before
    finally:
        await engine.dispose()
