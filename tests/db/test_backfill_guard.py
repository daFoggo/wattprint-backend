"""backfill_aggregates must not delete aggregates whose raw chunks were dropped by retention."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.services.aggregates import SkippedWindow, backfill_aggregates
from tests.db.conftest import _create_migrated_db

D = [datetime(2026, 2, d, tzinfo=UTC) for d in range(1, 7)]  # raw chunks are 1 day


@pytest.fixture
async def guard_conn():
    """Private migrated database (policies off) with 4 days of raw data, fully backfilled."""
    dsn, drop = await _create_migrated_db()
    engine = create_async_engine(dsn, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as c:
            await c.execute(text("SELECT ops.set_policies(false)"))
            home = uuid.uuid4()
            await c.execute(text("INSERT INTO core.home (id, name) VALUES (:i, 'G')"), {"i": home})
            sid = await c.scalar(text(
                "INSERT INTO energy.series (home_id, kind, metric, unit) "
                "VALUES (:h, 'main', 'power_w', 'W') RETURNING series_id"), {"h": home})
            for day in D[:4]:
                await c.execute(text(
                    "INSERT INTO energy.reading (ts, series_id, value) "
                    "SELECT g, :s, 100 FROM generate_series(CAST(:a AS timestamptz), "
                    "CAST(:b AS timestamptz), interval '10 seconds') g"),
                    {"s": sid, "a": day + timedelta(hours=2), "b": day + timedelta(hours=3)})
            assert await backfill_aggregates(c, D[0], D[5]) == []
            yield c, sid
    finally:
        await engine.dispose()
        await drop()


async def counts(c, sid) -> dict:
    return {v: await c.scalar(text(f"SELECT count(*) FROM energy.reading_{v} WHERE series_id = :s"),
                              {"s": sid}) for v in ("1m", "1h", "1d")}


async def drop_first_two_days(c):
    await c.execute(text(
        "SELECT drop_chunks('energy.reading', older_than => CAST(:t AS timestamptz))"), {"t": D[2]})
    assert await c.scalar(text("SELECT count(*) FROM energy.reading WHERE ts < :t"),
                          {"t": D[2]}) == 0


async def test_default_backfill_keeps_aggregates_of_dropped_raw(guard_conn):
    c, sid = guard_conn
    before = await counts(c, sid)
    assert before == {"1m": 4 * 61, "1h": 4 * 2, "1d": 4}
    await drop_first_two_days(c)
    assert await counts(c, sid) == before  # retention leaves the aggregates alone
    # late row in the surviving range must still be picked up
    await c.execute(text("INSERT INTO energy.reading (ts, series_id, value) VALUES (:t, :s, 100)"),
                    {"t": D[3] + timedelta(hours=12), "s": sid})
    skipped = await backfill_aggregates(c, D[0], D[5])
    assert await counts(c, sid) == {"1m": 4 * 61 + 1, "1h": 4 * 2 + 1, "1d": 4}
    reading = [w for w in skipped if "device_estimate" not in w.view]
    assert reading and all(isinstance(w, SkippedWindow) for w in reading)
    assert {w.view for w in reading} == {f"energy.reading_{r}" for r in ("1m", "1h", "1d")}
    for w in reading:
        assert w.from_ts < D[2] and w.to_ts <= D[2] + timedelta(days=1)
        assert w.reason == "older than the oldest raw chunk"
    # the dropped days' buckets are intact (the third 1 d bucket starts 17:00 the day before D3)
    rows = await c.scalar(text("SELECT count(*) FROM energy.reading_1d WHERE series_id = :s "
                               "AND bucket < :t"), {"s": sid, "t": D[2]})
    assert rows == 3


async def test_window_wholly_before_raw_is_skipped_and_reported(guard_conn):
    c, sid = guard_conn
    await drop_first_two_days(c)
    before = await counts(c, sid)
    skipped = await backfill_aggregates(c, D[0], D[1])
    assert {w.view for w in skipped if "device_estimate" not in w.view} == {
        f"energy.reading_{r}" for r in ("1m", "1h", "1d")}
    assert all(w.reason in ("older than the oldest raw chunk", "no raw rows for this range")
               for w in skipped)
    assert await counts(c, sid) == before


async def test_allow_missing_raw_behaves_as_before(guard_conn):
    c, sid = guard_conn
    await drop_first_two_days(c)
    skipped = await backfill_aggregates(c, D[0], D[5], allow_missing_raw=True)
    assert skipped == []
    # the two dropped days are now empty in every aggregate, the rest is kept
    assert await counts(c, sid) == {"1m": 2 * 61, "1h": 2 * 2, "1d": 2}


async def test_no_raw_chunk_at_all_skips_everything(guard_conn):
    c, sid = guard_conn
    await c.execute(text(
        "SELECT drop_chunks('energy.reading', older_than => CAST(:t AS timestamptz))"), {"t": D[5]})
    before = await counts(c, sid)
    skipped = await backfill_aggregates(c, D[0], D[5])
    assert {w.view for w in skipped if "device_estimate" not in w.view} == {
        f"energy.reading_{r}" for r in ("1m", "1h", "1d")}
    assert all(w.reason == "no raw rows for this range" for w in skipped)
    assert await counts(c, sid) == before
