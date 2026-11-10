"""backfill_aggregates must not delete or shrink aggregates whose raw rows are gone."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.services.aggregates import SKIP_REASON, SkippedWindow, backfill_aggregates
from tests.db.conftest import _create_migrated_db

D = [datetime(2026, 2, d, tzinfo=UTC) for d in range(1, 10)]  # raw chunks are 1 day


def day_start(i: int) -> datetime:
    """Start (17:00 UTC the day before) of the local day that holds D[i] 02:00 UTC."""
    return D[i] - timedelta(hours=7)


@pytest.fixture
async def guard_conn():
    """Private migrated database (policies off) with 6 days of raw data, fully backfilled."""
    dsn, drop = await _create_migrated_db()
    engine = create_async_engine(dsn, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as c:
            await c.execute(text("SELECT public.set_policies(false)"))
            home = await c.scalar(text("INSERT INTO public.tb_home (name) VALUES ('G') RETURNING id"))
            sid = await c.scalar(
                text(
                    "INSERT INTO public.tb_series (home_id, kind, metric, unit) "
                    "VALUES (:h, 'main', 'power_w', 'W') RETURNING series_id"
                ),
                {"h": home},
            )
            for day in D[:6]:
                await load_day(c, sid, day)
            assert await backfill_aggregates(c, D[0], D[8]) == []  # fresh history: nothing skipped
            yield c, sid
    finally:
        await engine.dispose()
        await drop()


async def load_day(c, sid, day):
    await c.execute(
        text(
            "INSERT INTO public.tb_reading (ts, series_id, value) "
            "SELECT g, :s, 100 FROM generate_series(CAST(:a AS timestamptz), "
            "CAST(:b AS timestamptz), interval '10 seconds') g"
        ),
        {"s": sid, "a": day + timedelta(hours=2), "b": day + timedelta(hours=3)},
    )


async def snapshot(c, sid) -> dict:
    out = {}
    for v in ("1m", "1h", "1d"):
        res = await c.execute(
            text(f"SELECT bucket, n FROM public.reading_{v} WHERE series_id = :s ORDER BY bucket"),
            {"s": sid},
        )
        out[v] = [tuple(r) for r in res]
    return out


async def drop_chunks_between(c, newer, older):
    await c.execute(
        text(
            "SELECT drop_chunks('public.tb_reading', older_than => CAST(:o AS timestamptz), "
            "newer_than => CAST(:n AS timestamptz))"
        ),
        {"o": older, "n": newer},
    )


def reading_windows(skipped):
    return [w for w in skipped if "device_estimate" not in w.view]


async def test_default_backfill_keeps_aggregates_of_dropped_raw(guard_conn):
    c, sid = guard_conn
    before = await snapshot(c, sid)
    assert [len(before[v]) for v in ("1m", "1h", "1d")] == [6 * 61, 6 * 2, 6]
    await c.execute(
        text("SELECT drop_chunks('public.tb_reading', older_than => CAST(:t AS timestamptz))"),
        {"t": D[2]},
    )
    assert await snapshot(c, sid) == before  # retention leaves the aggregates alone
    # a late row in the surviving range must still be picked up
    late = D[3] + timedelta(hours=12)
    await c.execute(
        text("INSERT INTO public.tb_reading (ts, series_id, value) VALUES (:t, :s, 100)"),
        {"t": late, "s": sid},
    )
    skipped = await backfill_aggregates(c, D[0], D[8])
    after = await snapshot(c, sid)
    assert after["1m"] == sorted(before["1m"] + [(late, 1)])
    assert len(after["1h"]) == 6 * 2 + 1 and len(after["1d"]) == 6
    ours = reading_windows(skipped)
    assert {w.view for w in ours} == {f"public.reading_{r}" for r in ("1m", "1h", "1d")}
    for w in ours:
        assert isinstance(w, SkippedWindow) and w.reason == SKIP_REASON
        assert w.from_ts <= D[0] + timedelta(hours=1) and w.to_ts == day_start(2)


async def test_isolated_old_chunk_does_not_defeat_the_guard(guard_conn):
    """A misdated row older than retention recreates an old chunk (the probe of the review)."""
    c, sid = guard_conn
    before = await snapshot(c, sid)
    await c.execute(
        text("SELECT drop_chunks('public.tb_reading', older_than => CAST(:t AS timestamptz))"),
        {"t": D[3]},
    )
    stray = D[0] + timedelta(hours=12)
    await c.execute(
        text("INSERT INTO public.tb_reading (ts, series_id, value) VALUES (:t, :s, 5)"),
        {"t": stray, "s": sid},
    )
    skipped = await backfill_aggregates(c, D[0] - timedelta(days=1), D[8])
    assert await snapshot(c, sid) == before  # hour and day buckets of D1 keep n=360 and n=361
    ours = reading_windows(skipped)
    assert {w.view for w in ours} == {f"public.reading_{r}" for r in ("1m", "1h", "1d")}
    # the 1 h and 1 d views agree about the stray day (no half-refreshed day)
    h = await c.scalar(
        text(
            "SELECT sum(n) FROM public.reading_1h WHERE series_id = :s AND bucket >= :a "
            "AND bucket < :b"
        ),
        {"s": sid, "a": day_start(0), "b": day_start(1)},
    )
    d = await c.scalar(
        text("SELECT n FROM public.reading_1d WHERE series_id = :s AND bucket = :a"),
        {"s": sid, "a": day_start(0)},
    )
    assert h == d == 361


async def test_gap_in_the_middle_from_manual_drop_chunks(guard_conn):
    c, sid = guard_conn
    before = await snapshot(c, sid)
    await drop_chunks_between(c, D[2] - timedelta(seconds=1), D[3])  # the chunk of D3 only
    assert (
        await c.scalar(
            text("SELECT count(*) FROM public.tb_reading WHERE ts >= :a AND ts < :b"),
            {"a": D[2], "b": D[3]},
        )
        == 0
    )
    late = D[4] + timedelta(hours=12)
    await c.execute(
        text("INSERT INTO public.tb_reading (ts, series_id, value) VALUES (:t, :s, 100)"),
        {"t": late, "s": sid},
    )
    skipped = await backfill_aggregates(c, D[0], D[8])
    after = await snapshot(c, sid)
    assert after["1m"] == sorted(before["1m"] + [(late, 1)])
    assert len(after["1d"]) == 6  # the gap day keeps its bucket
    ours = reading_windows(skipped)
    assert {w.view for w in ours} == {f"public.reading_{r}" for r in ("1m", "1h", "1d")}
    for w in ours:  # exactly the gap day (the local day that holds D3 02:00)
        assert (w.from_ts, w.to_ts) == (day_start(2), day_start(3))


async def test_fresh_history_and_late_rows_are_refreshed_normally(guard_conn):
    c, sid = guard_conn
    before = await snapshot(c, sid)
    await load_day(c, sid, D[6])  # new, not yet materialized history
    late = D[1] + timedelta(hours=12)  # late row inside the materialized range
    await c.execute(
        text("INSERT INTO public.tb_reading (ts, series_id, value) VALUES (:t, :s, 100)"),
        {"t": late, "s": sid},
    )
    assert await backfill_aggregates(c, D[0], D[8]) == []
    after = await snapshot(c, sid)
    assert len(after["1m"]) == len(before["1m"]) + 61 + 1
    assert (late, 1) in after["1m"]
    assert len(after["1d"]) == 7


async def test_allow_missing_raw_behaves_as_before(guard_conn):
    c, sid = guard_conn
    await c.execute(
        text("SELECT drop_chunks('public.tb_reading', older_than => CAST(:t AS timestamptz))"),
        {"t": D[2]},
    )
    assert await backfill_aggregates(c, D[0], D[8], allow_missing_raw=True) == []
    after = await snapshot(c, sid)
    # the buckets of the two dropped days are gone, the four surviving days are refreshed
    assert [len(after[v]) for v in ("1m", "1h", "1d")] == [4 * 61, 4 * 2, 4]


async def test_no_raw_chunk_at_all_skips_everything_materialized(guard_conn):
    c, sid = guard_conn
    await c.execute(
        text("SELECT drop_chunks('public.tb_reading', older_than => CAST(:t AS timestamptz))"),
        {"t": D[7]},
    )
    before = await snapshot(c, sid)
    skipped = await backfill_aggregates(c, D[0], D[8])
    assert {w.view for w in reading_windows(skipped)} == {
        f"public.reading_{r}" for r in ("1m", "1h", "1d")
    }
    assert await snapshot(c, sid) == before


async def second_series(c):
    home = await c.scalar(text("INSERT INTO public.tb_home (name) VALUES ('G2') RETURNING id"))
    return await c.scalar(
        text(
            "INSERT INTO public.tb_series (home_id, kind, metric, unit) "
            "VALUES (:h, 'main', 'power_w', 'W') RETURNING series_id"
        ),
        {"h": home},
    )


async def test_other_series_cannot_mask_a_loss(guard_conn):
    """Totals would balance (raw >= materialized); the per-series comparison still catches it."""
    c, sid = guard_conn
    other = await second_series(c)
    await load_day(c, other, D[2])
    await backfill_aggregates(c, D[0], D[8])
    before = await snapshot(c, sid)
    day = {"s": sid, "a": D[2], "b": D[3]}
    await c.execute(
        text("DELETE FROM public.tb_reading WHERE series_id = :s AND ts >= :a AND ts < :b"), day
    )  # simulate lost rows of the first series
    for k in range(3):  # many new rows of the other series on the same day
        await c.execute(
            text(
                "INSERT INTO public.tb_reading (ts, series_id, value) "
                "SELECT g, :s, 1 FROM generate_series(CAST(:a AS timestamptz), "
                "CAST(:b AS timestamptz), interval '10 seconds') g "
                "ON CONFLICT DO NOTHING"
            ),
            {"s": other, "a": D[2] + timedelta(hours=5 + k), "b": D[2] + timedelta(hours=6 + k)},
        )
    skipped = await backfill_aggregates(c, D[0], D[8])
    assert await snapshot(c, sid) == before
    assert {(w.from_ts, w.to_ts) for w in reading_windows(skipped) if "1d" in w.view} == {
        (day_start(2), day_start(3))
    }


async def test_orphaned_aggregates_of_a_deleted_series_do_not_block(guard_conn):
    c, sid = guard_conn
    gone = await second_series(c)
    await load_day(c, gone, D[2])
    await backfill_aggregates(c, D[0], D[8])
    await c.execute(text("DELETE FROM public.tb_reading WHERE series_id = :s"), {"s": gone})
    await c.execute(text("DELETE FROM public.tb_series WHERE series_id = :s"), {"s": gone})
    late = D[2] + timedelta(hours=12)
    await c.execute(
        text("INSERT INTO public.tb_reading (ts, series_id, value) VALUES (:t, :s, 1)"),
        {"t": late, "s": sid},
    )
    assert await backfill_aggregates(c, D[0], D[8]) == []  # orphans are ignored
    assert (late, 1) in (await snapshot(c, sid))["1m"]
