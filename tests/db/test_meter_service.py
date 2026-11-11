import re
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import event, text

from app.modules.energy.services import meter
from app.modules.energy.services.meter import (
    device_breakdown,
    latest_power,
    meter_series,
    pick_step,
)


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=UTC)


# Note: these tests rely on uncommitted rows at a fixed past date and on an empty scratch DB;
# real-time aggregation shows them without a refresh. A refresh policy on a populated database
# could move the continuous aggregate watermark and hide them.
T0 = utc(2026, 10, 1, 17)  # local midnight (17:00 UTC)
FAR = utc(2030, 1, 1)  # a "now" well past every test row


async def new_home(session) -> tuple[int, int]:
    hid = await session.scalar(
        text("INSERT INTO public.tb_home (name) VALUES ('Meter') RETURNING id")
    )
    sid = await session.scalar(
        text(
            "INSERT INTO public.tb_series (home_id, kind, metric, unit) "
            "VALUES (:h, 'main', 'power_w', 'W') RETURNING series_id"
        ),
        {"h": hid},
    )
    return hid, sid


async def new_device(session, hid, name="Fridge") -> tuple[int, int]:
    did = await session.scalar(
        text(
            "INSERT INTO public.tb_device (home_id, device_type_code, name, origin) "
            "VALUES (:h, 'fridge', :n, 'nilm') RETURNING id"
        ),
        {"h": hid, "n": name},
    )
    sid = await session.scalar(
        text(
            "INSERT INTO public.tb_series (home_id, kind, device_id, metric, unit) "
            "VALUES (:h, 'device', :d, 'power_w', 'W') RETURNING series_id"
        ),
        {"h": hid, "d": did},
    )
    return did, sid


async def put(session, sid, ts, watts, table="reading"):
    await session.execute(
        text(f"INSERT INTO public.tb_{table} (ts, series_id, value) VALUES (:t, :s, :v)"),
        {"t": ts, "s": sid, "v": watts},
    )


async def load(session, sid, start, minutes, watts, table="reading"):
    """One reading per minute at constant power."""
    await session.execute(
        text(
            f"INSERT INTO public.tb_{table} (ts, series_id, value) "
            "SELECT CAST(:s AS timestamptz) + g * interval '1 minute', :sid, :w "
            "FROM generate_series(0, :n - 1) g"
        ),
        {"s": start, "sid": sid, "w": watts, "n": minutes},
    )


# --- pick_step ---


def test_pick_step_ladder():
    # The finest step whose bucket count ceil(window / step) is <= max_points.
    def step(span, pts=600):
        return pick_step(T0, T0 + span, pts)

    assert step(timedelta(hours=1)) == "1m"  # 60 buckets
    assert step(timedelta(hours=10)) == "1m"  # exactly 600
    assert step(timedelta(hours=10, minutes=1)) == "5m"  # 601 at 1m
    assert step(timedelta(days=1)) == "5m"  # 288 (1m: 1440)
    assert step(timedelta(days=7)) == "30m"  # 336 (15m: 672)
    assert step(timedelta(days=30)) == "3h"  # 240 (1h: 720)
    assert step(timedelta(days=90)) == "6h"  # 360 (3h: 720)
    assert step(timedelta(days=90), 2000) == "3h"  # 720 (1h: 2160)
    assert step(timedelta(days=30), 2000) == "30m"  # 1440 (15m: 2880)
    assert step(timedelta(days=45), 2000) == "1h"  # 1080 (30m: 2160)
    assert step(timedelta(hours=1, seconds=1), 60) == "5m"  # ceil: 61 buckets at 1m
    assert pick_step(T0, T0 + timedelta(days=1), 1) == "1d"


def test_pick_step_falls_back_to_1d():
    assert pick_step(T0, T0 + timedelta(days=90), 50) == "1d"  # 6h would give 360 buckets
    assert pick_step(T0, T0 + timedelta(days=90), 1) == "1d"


def test_pick_step_validation():
    until = T0 + timedelta(days=1)
    with pytest.raises(ValueError):
        pick_step(datetime(2026, 10, 1), until, 600)  # naive since
    with pytest.raises(ValueError):
        pick_step(T0, datetime(2026, 10, 2), 600)  # naive until
    with pytest.raises(ValueError):
        pick_step(T0, T0, 600)
    with pytest.raises(ValueError):
        pick_step(T0, T0 - timedelta(hours=1), 600)
    with pytest.raises(ValueError):
        pick_step(T0, T0 + timedelta(days=90, seconds=1), 600)
    pick_step(T0, T0 + timedelta(days=90), 600)  # 90 days exactly is allowed
    for bad in (0, 2001, -1):
        with pytest.raises(ValueError):
            pick_step(T0, until, bad)
    pick_step(T0, until, 1)
    pick_step(T0, until, 2000)


# --- meter_series ---


async def test_meter_series_each_step_rebuckets_correctly(session):
    hid, sid = await new_home(session)
    # Three samples in one minute: avg 200, min 100, max 300, 3 samples.
    for i, v in enumerate((100, 200, 300)):
        await put(session, sid, T0 + timedelta(seconds=10 * i), v)
    # Minute 1: one sample of 600 W. Together with minute 0: weighted avg (3*200+600)/4 = 300.
    await put(session, sid, T0 + timedelta(minutes=1), 600)
    # 17:04 UTC is in the same 5m bucket; 17:05 starts the next one.
    await put(session, sid, T0 + timedelta(minutes=4), 1200)
    await put(session, sid, T0 + timedelta(minutes=5), 60)
    # 40 minutes later: the second 30m bucket, still within the first 1h bucket.
    await put(session, sid, T0 + timedelta(minutes=40), 900)
    # 2h later: a different 1h bucket but the same 3h bucket.
    await put(session, sid, T0 + timedelta(hours=2), 120)
    # 3h30 later: next 3h bucket, same 6h bucket.
    await put(session, sid, T0 + timedelta(hours=3, minutes=30), 480)
    # Next local day.
    await put(session, sid, T0 + timedelta(days=1, minutes=1), 360)

    def wh(w):
        return w * 60 / 3600

    day = timedelta(days=1)

    async def at(step_window, max_points):
        pts = await meter_series(session, hid, T0, T0 + step_window, max_points, FAR)
        return {p.ts: p for p in pts}

    # 1m: one point per minute that has data, no fill.
    p = await at(timedelta(hours=1), 600)
    assert p[T0].avg_w == pytest.approx(200) and (p[T0].min_w, p[T0].max_w) == (100, 300)
    assert p[T0].energy_wh == pytest.approx(wh(200))
    assert list(p)[:2] == [T0, T0 + timedelta(minutes=1)]
    assert p[T0 + timedelta(minutes=1)].avg_w == pytest.approx(600)

    # 5m: minutes 0, 1, 4 -> samples 3x(100..300) + 600 + 1200 => weighted avg
    p = await at(timedelta(days=1), 600)  # picks 5m
    b = p[T0]
    assert b.avg_w == pytest.approx((3 * 200 + 600 + 1200) / 5)
    assert (b.min_w, b.max_w) == (100, 1200)
    assert b.energy_wh == pytest.approx(wh(200 + 600 + 1200))
    assert p[T0 + timedelta(minutes=5)].avg_w == pytest.approx(60)

    # 30m: the 17:40 sample is alone in the second bucket.
    p = await at(timedelta(days=7), 600)  # picks 30m
    b = p[T0]
    assert b.avg_w == pytest.approx((3 * 200 + 600 + 1200 + 60) / 6)
    assert (b.min_w, b.max_w) == (60, 1200)
    assert b.energy_wh == pytest.approx(wh(200 + 600 + 1200 + 60))
    assert p[T0 + timedelta(minutes=30)].avg_w == pytest.approx(900)
    assert p[T0 + timedelta(hours=2)].avg_w == pytest.approx(120)

    # 1h: the same minute rows summed per hour.
    p = await at(timedelta(days=45), 2000)  # picks 1h
    b = p[T0]
    assert b.avg_w == pytest.approx((3 * 200 + 600 + 1200 + 60 + 900) / 7)
    assert (b.min_w, b.max_w) == (60, 1200)
    assert b.energy_wh == pytest.approx(wh(200 + 600 + 1200 + 60 + 900))
    assert p[T0 + timedelta(hours=2)].avg_w == pytest.approx(120)

    # 3h (origin 17:00 UTC): hours 17:00..19:59 form one bucket, 20:00 starts the next.
    p = await at(timedelta(days=30), 300)  # 3h gives 240 buckets, 1h gives 720
    assert meter.pick_step(T0, T0 + timedelta(days=30), 300) == "3h"
    b = p[T0]
    assert b.avg_w == pytest.approx((3 * 200 + 600 + 1200 + 60 + 900 + 120) / 8)
    assert b.energy_wh == pytest.approx(wh(200 + 600 + 1200 + 60 + 900 + 120))
    assert (b.min_w, b.max_w) == (60, 1200)
    assert p[T0 + timedelta(hours=3)].avg_w == pytest.approx(480)

    # 6h: 17:00..22:59 in one bucket.
    assert meter.pick_step(T0, T0 + timedelta(days=90), 600) == "6h"
    pts = await meter_series(session, hid, T0, T0 + timedelta(days=90), 600, FAR)
    b = pts[0]
    assert b.ts == T0
    assert b.avg_w == pytest.approx((3 * 200 + 600 + 1200 + 60 + 900 + 120 + 480) / 9)
    assert b.energy_wh == pytest.approx(wh(200 + 600 + 1200 + 60 + 900 + 120 + 480))

    # 1d: two local days, the daily bucket starts at 17:00 UTC.
    pts = await meter_series(session, hid, T0, T0 + timedelta(days=90), 50, FAR)
    assert [x.ts for x in pts] == [T0, T0 + day]
    assert pts[0].avg_w == pytest.approx((3 * 200 + 600 + 1200 + 60 + 900 + 120 + 480) / 9)
    assert pts[1].avg_w == pytest.approx(360)
    assert (pts[0].min_w, pts[0].max_w) == (60, 1200)


async def test_meter_series_bucket_alignment_at_local_midnight(session):
    hid, sid = await new_home(session)
    await put(session, sid, utc(2026, 10, 2, 16, 59, 59), 100)  # last second of local day 1
    await put(session, sid, utc(2026, 10, 2, 17, 0, 0), 200)  # first second of local day 2
    pts = await meter_series(session, hid, T0, T0 + timedelta(days=90), 50, FAR)  # 1d
    assert [(p.ts, p.avg_w) for p in pts] == [
        (T0, pytest.approx(100)),
        (utc(2026, 10, 2, 17), pytest.approx(200)),
    ]
    # 6h re-bucket: 16:59 belongs to the 11:00-17:00 bucket, 17:00 to the next one.
    pts = await meter_series(session, hid, T0, T0 + timedelta(days=90), 600, FAR)
    assert [p.ts for p in pts] == [utc(2026, 10, 2, 11), utc(2026, 10, 2, 17)]


async def test_meter_series_excludes_open_minute(session):
    hid, sid = await new_home(session)
    await put(session, sid, T0, 100)
    await put(session, sid, T0 + timedelta(minutes=1), 200)
    await put(session, sid, T0 + timedelta(minutes=2, seconds=5), 300)  # the open minute
    now = T0 + timedelta(minutes=2, seconds=30)
    pts = await meter_series(session, hid, T0, T0 + timedelta(hours=1), 600, now)
    assert [p.ts for p in pts] == [T0, T0 + timedelta(minutes=1)]
    # Exactly on a minute boundary the minute that just ended is closed and returned.
    pts = await meter_series(
        session, hid, T0, T0 + timedelta(hours=1), 600, T0 + timedelta(minutes=3)
    )
    assert [p.ts for p in pts] == [T0, T0 + timedelta(minutes=1), T0 + timedelta(minutes=2)]
    # A coarser bucket that holds the open minute is returned, and is partial by nature.
    pts = await meter_series(session, hid, T0, T0 + timedelta(days=7), 600, now)
    assert [p.ts for p in pts] == [T0]
    assert pts[0].avg_w == pytest.approx(150)  # only the two closed minutes


async def test_meter_series_15m_step_alignment(session):
    hid, sid = await new_home(session)
    assert pick_step(T0, T0 + timedelta(days=5), 600) == "15m"
    for m in (0, 14, 15, 29, 30):
        await put(session, sid, T0 + timedelta(minutes=m), 100 * (m + 1))
    pts = await meter_series(session, hid, T0, T0 + timedelta(days=5), 600, FAR)
    assert [p.ts for p in pts] == [T0 + timedelta(minutes=m) for m in (0, 15, 30)]
    assert pts[0].avg_w == pytest.approx((100 + 1500) / 2)
    assert pts[1].avg_w == pytest.approx((1600 + 3000) / 2)


async def test_meter_series_window_is_bucket_granular(session):
    """An unaligned `until` inside a bucket returns that bucket whole, at every step."""
    hid, sid = await new_home(session)
    await load(session, sid, T0, 24 * 60, 600)  # 600 W every minute: 10 Wh per minute
    m = timedelta

    async def run(until, max_points, step):
        assert pick_step(T0, until, max_points) == step
        return await meter_series(session, hid, T0, until, max_points, FAR)

    # 5m: until 17:07 -> buckets 17:00 and 17:05, the latter whole (5 minutes).
    pts = await run(T0 + m(minutes=7), 2, "5m")
    assert [p.ts for p in pts] == [T0, T0 + m(minutes=5)]
    assert pts[-1].energy_wh == pytest.approx(50.0)
    # 15m: until 17:20 -> 17:15 bucket whole.
    pts = await run(T0 + m(minutes=20), 2, "15m")
    assert [p.ts for p in pts] == [T0, T0 + m(minutes=15)]
    assert pts[-1].energy_wh == pytest.approx(150.0)
    # 30m: until 17:40 -> 17:30 bucket whole, not cut at 17:40.
    pts = await run(T0 + m(minutes=40), 2, "30m")
    assert [p.ts for p in pts] == [T0, T0 + m(minutes=30)]
    assert pts[-1].energy_wh == pytest.approx(300.0)
    # 1h: until 19:20 -> 19:00 bucket whole.
    pts = await run(T0 + m(hours=2, minutes=20), 3, "1h")
    assert [p.ts for p in pts] == [T0 + m(hours=h) for h in (0, 1, 2)]
    assert pts[-1].energy_wh == pytest.approx(600.0)
    # 3h: until 20:30 -> 20:00 bucket whole (3 hours).
    pts = await run(T0 + m(hours=3, minutes=30), 2, "3h")
    assert [p.ts for p in pts] == [T0, T0 + m(hours=3)]
    assert pts[-1].energy_wh == pytest.approx(1800.0)
    # 6h: until 23:30 -> second 6h bucket (23:00) whole.
    pts = await run(T0 + m(hours=6, minutes=30), 2, "6h")
    assert [p.ts for p in pts] == [T0, T0 + m(hours=6)]
    assert pts[-1].energy_wh == pytest.approx(3600.0)
    # 1d: until 7 h into the day -> the whole day bucket (not cut at 7 h).
    pts = await run(T0 + m(hours=7), 1, "1d")
    assert [p.ts for p in pts] == [T0]
    assert pts[0].energy_wh == pytest.approx(24 * 60 * 10.0)


async def test_meter_series_open_minute_is_capped_at_30m_but_not_at_1h(session):
    hid, sid = await new_home(session)
    await put(session, sid, T0, 100)
    await put(session, sid, T0 + timedelta(minutes=1), 300)  # closed minute
    await put(session, sid, T0 + timedelta(minutes=2, seconds=5), 500)  # the open minute
    now = T0 + timedelta(minutes=2, seconds=30)
    assert pick_step(T0, T0 + timedelta(days=7), 600) == "30m"
    p30 = await meter_series(session, hid, T0, T0 + timedelta(days=7), 600, now)
    assert p30[0].avg_w == pytest.approx(200)  # closed minutes only
    assert pick_step(T0, T0 + timedelta(days=45), 2000) == "1h"
    p1h = await meter_series(session, hid, T0, T0 + timedelta(days=45), 2000, now)
    assert p1h[0].avg_w == pytest.approx(300)  # real-time data up to the present instant


async def test_meter_series_until_is_exclusive_and_since_floors_to_step(session):
    hid, sid = await new_home(session)
    for m in range(0, 10):
        await put(session, sid, T0 + timedelta(minutes=m), 100)
    pts = await meter_series(
        session, hid, T0 + timedelta(minutes=2, seconds=30), T0 + timedelta(minutes=5), 600, FAR
    )
    # since floors to its 1m bucket (00:02), until is exclusive.
    assert [p.ts for p in pts] == [T0 + timedelta(minutes=m) for m in (2, 3, 4)]


async def test_meter_series_no_gap_fill(session):
    hid, sid = await new_home(session)
    await put(session, sid, T0, 100)
    await put(session, sid, T0 + timedelta(minutes=30), 200)
    pts = await meter_series(session, hid, T0, T0 + timedelta(hours=1), 600, FAR)
    assert [p.ts for p in pts] == [T0, T0 + timedelta(minutes=30)]
    # Same at a coarse step: empty days between two data days are not invented.
    await put(session, sid, T0 + timedelta(days=5), 300)
    pts = await meter_series(session, hid, T0, T0 + timedelta(days=90), 50, FAR)
    assert [p.ts for p in pts] == [T0, T0 + timedelta(days=5)]


async def test_meter_series_unknown_home_is_empty(session):
    assert await meter_series(session, -1, T0, T0 + timedelta(days=1), 600, FAR) == []
    hid = await session.scalar(
        text("INSERT INTO public.tb_home (name) VALUES ('Empty') RETURNING id")
    )
    assert await meter_series(session, hid, T0, T0 + timedelta(days=1), 600, FAR) == []
    hid2, _ = await new_home(session)
    assert await meter_series(session, hid2, T0, T0 + timedelta(days=1), 600, FAR) == []


async def test_meter_series_rejects_naive_datetimes(session):
    hid = -1
    with pytest.raises(ValueError):
        await meter_series(session, hid, datetime(2026, 10, 1), T0 + timedelta(days=1))
    with pytest.raises(ValueError):
        await meter_series(session, hid, T0, T0 + timedelta(days=1), now=datetime(2026, 10, 1))


async def test_other_homes_are_never_included(session):
    a, sa = await new_home(session)
    b, sb = await new_home(session)
    await load(session, sa, T0, 60, 100)
    await load(session, sb, T0, 60, 5000)
    pts = await meter_series(session, a, T0, T0 + timedelta(hours=1), 600, FAR)
    assert len(pts) == 60 and {p.avg_w for p in pts} == {100.0}
    pts = await meter_series(session, b, T0, T0 + timedelta(hours=1), 600, FAR)
    assert {p.avg_w for p in pts} == {5000.0}
    la = await latest_power(session, a, T0 + timedelta(hours=2))
    assert la.watts == 100
    # Devices of one home do not leak into the other's breakdown.
    da, dsa = await new_device(session, a, "A-fridge")
    db_, dsb = await new_device(session, b, "B-fridge")
    await load(session, dsa, T0, 60, 60, "device_estimate")
    await load(session, dsb, T0, 60, 600, "device_estimate")
    bd = await device_breakdown(session, a, T0, T0 + timedelta(hours=2))
    assert [d.device_id for d in bd] == [da]
    assert bd[0].kwh == pytest.approx(0.06) and bd[0].share == pytest.approx(1.0)


async def test_meter_series_never_touches_raw_tables(session):
    hid, sid = await new_home(session)
    await load(session, sid, T0, 5, 100)
    did, dsid = await new_device(session, hid)
    await load(session, dsid, T0, 5, 50, "device_estimate")
    seen: list[str] = []

    def spy(conn_, cursor, statement, parameters, context, executemany):
        seen.append(statement)

    event.listen(session.bind.sync_engine, "before_cursor_execute", spy)
    try:
        await meter_series(session, hid, T0, T0 + timedelta(hours=1), 600, FAR)  # 1m
        await meter_series(session, hid, T0, T0 + timedelta(days=1), 600, FAR)  # 5m
        await meter_series(session, hid, T0, T0 + timedelta(days=5), 600, FAR)  # 15m
        await meter_series(session, hid, T0, T0 + timedelta(days=7), 600, FAR)  # 30m
        await meter_series(session, hid, T0, T0 + timedelta(days=90), 600, FAR)  # 6h
        await meter_series(session, hid, T0, T0 + timedelta(days=45), 2000, FAR)  # 1h
        await meter_series(session, hid, T0, T0 + timedelta(days=30), 300, FAR)  # 3h
        await meter_series(session, hid, T0, T0 + timedelta(days=90), 50, FAR)  # 1d
        await latest_power(session, hid, T0 + timedelta(hours=1))
        await device_breakdown(session, hid, T0, T0 + timedelta(hours=2))
        await device_breakdown(session, hid, T0, T0 + timedelta(days=10))
    finally:
        event.remove(session.bind.sync_engine, "before_cursor_execute", spy)
    energy = [s for s in seen if "public." in s]
    assert len(energy) >= 11
    raw = re.compile(r"\benergy\.(reading|device_estimate)\b")
    assert not [s for s in seen if raw.search(s)]
    joined = " ".join(seen)
    for view in (
        "reading_1m",
        "reading_1h",
        "reading_1d",
        "device_estimate_1h",
        "device_estimate_1d",
    ):
        assert f"public.{view}" in joined


# --- latest_power ---


async def test_latest_power(session):
    hid, sid = await new_home(session)
    await put(session, sid, T0, 100)
    await put(session, sid, T0 + timedelta(minutes=1), 250)
    await put(session, sid, T0 + timedelta(minutes=1, seconds=40), 300)  # last_w of minute 1
    await put(session, sid, T0 + timedelta(minutes=2, seconds=5), 999)  # open minute
    now = T0 + timedelta(minutes=2, seconds=30)
    lp = await latest_power(session, hid, now)
    assert lp == meter.LatestPower(T0 + timedelta(minutes=1), 300.0)
    # Once the minute closes it becomes the newest.
    lp = await latest_power(session, hid, T0 + timedelta(minutes=3))
    assert lp == meter.LatestPower(T0 + timedelta(minutes=2), 999.0)


async def test_latest_power_none_when_old_or_missing(session):
    hid, sid = await new_home(session)
    assert await latest_power(session, hid, T0) is None  # series, no data
    assert await latest_power(session, -1, T0) is None  # unknown home
    await put(session, sid, T0, 100)
    now = T0 + timedelta(days=7, minutes=1)
    assert await latest_power(session, hid, now) is None  # older than 7 days
    assert (await latest_power(session, hid, T0 + timedelta(days=6))).watts == 100


async def test_latest_power_query_is_bounded(session):
    hid, sid = await new_home(session)
    await load(session, sid, T0, 30, 100)
    now = T0 + timedelta(hours=1)
    sql, params = meter._latest_statement(sid, now)
    plan = "\n".join(r[0] for r in (await session.execute(text("EXPLAIN " + sql), params)).all())
    assert "LIMIT" in sql.upper() and "ORDER BY bucket DESC" in sql
    # The query always bounds the scan by series_id and a bucket range, so the planner can
    # exclude chunks and use the primary-key/bucket index instead of reading everything.
    assert "bucket >= :lo" in sql and "bucket < :hi" in sql
    assert params["sid"] == sid and params["hi"] - params["lo"] == timedelta(days=7)
    assert re.search(rf"series_id = {sid}(?!\d)", plan)  # equality on the series, not a scan of all
    assert re.search(r"^Limit", plan)  # stops at the first (newest) row


# --- device_breakdown ---


async def test_device_breakdown_shares_sum_to_one(session):
    hid, _ = await new_home(session)
    d1, s1 = await new_device(session, hid, "Fridge")
    d2, s2 = await new_device(session, hid, "Kettle")
    d3, s3 = await new_device(session, hid, "Idle")  # no data: omitted
    await load(session, s1, T0, 120, 100, "device_estimate")  # 200 Wh = 0.2 kWh
    await load(session, s2, T0, 60, 600, "device_estimate")  # 600 Wh = 0.6 kWh
    out = await device_breakdown(session, hid, T0, T0 + timedelta(hours=3))
    assert [d.device_id for d in out] == [d2, d1]
    assert [d.kwh for d in out] == [pytest.approx(0.6), pytest.approx(0.2)]
    assert [d.share for d in out] == [pytest.approx(0.75), pytest.approx(0.25)]
    assert sum(d.share for d in out) == pytest.approx(1.0)
    assert d3 not in [d.device_id for d in out]


async def test_device_breakdown_switches_to_daily_view_over_3_days(session):
    hid, _ = await new_home(session)
    did, sid = await new_device(session, hid)
    await load(session, sid, T0, 60, 1000, "device_estimate")  # 1 kWh on day 1
    eng = session.bind.sync_engine

    async def run(until):
        seen: list[str] = []

        def spy(conn_, cursor, statement, parameters, context, executemany):
            seen.append(statement)

        event.listen(eng, "before_cursor_execute", spy)
        try:
            out = await device_breakdown(session, hid, T0, until)
        finally:
            event.remove(eng, "before_cursor_execute", spy)
        return out, " ".join(seen)

    short, sql = await run(T0 + timedelta(days=3))
    assert short[0].kwh == pytest.approx(1.0)
    assert "device_estimate_1h" in sql and "device_estimate_1d" not in sql
    long_, sql = await run(T0 + timedelta(days=3, seconds=1))
    assert long_[0].kwh == pytest.approx(1.0)
    assert "device_estimate_1d" in sql and "device_estimate_1h" not in sql


async def test_device_breakdown_window_is_widened_to_whole_buckets(session):
    hid, _ = await new_home(session)
    did, sid = await new_device(session, hid)
    await load(session, sid, T0, 180, 100, "device_estimate")  # 100 Wh per hour, 3 hours
    one_h = timedelta(hours=1)
    out = await device_breakdown(session, hid, T0 + one_h, T0 + 2 * one_h)  # aligned: 1 bucket
    assert out[0].kwh == pytest.approx(0.1)
    half = timedelta(minutes=30)  # unaligned 1-hour window: two whole hourly buckets
    out = await device_breakdown(session, hid, T0 + one_h + half, T0 + 2 * one_h + half)
    assert out[0].kwh == pytest.approx(0.2)


async def test_device_breakdown_ties_are_ordered_by_device_id(session):
    hid, _ = await new_home(session)
    ids = []
    for name in ("A", "B", "C"):
        did, sid = await new_device(session, hid, name)
        await load(session, sid, T0, 60, 100, "device_estimate")
        ids.append(did)
    out = await device_breakdown(session, hid, T0, T0 + timedelta(hours=2))
    assert [d.device_id for d in out] == sorted(ids, key=str)


async def test_device_breakdown_empty_and_zero_energy(session):
    hid, _ = await new_home(session)
    assert await device_breakdown(session, hid, T0, T0 + timedelta(days=1)) == []
    assert await device_breakdown(session, -1, T0, T0 + timedelta(days=1)) == []
    did, sid = await new_device(session, hid)
    assert await device_breakdown(session, hid, T0, T0 + timedelta(days=1)) == []  # no data
    await load(session, sid, T0, 10, 0, "device_estimate")  # data, zero energy
    out = await device_breakdown(session, hid, T0, T0 + timedelta(days=1))
    assert out == [meter.DeviceEnergy(did, 0.0, 0.0)]


async def test_device_breakdown_validation(session):
    hid = -1
    with pytest.raises(ValueError):
        await device_breakdown(session, hid, datetime(2026, 10, 1), T0 + timedelta(days=1))
    with pytest.raises(ValueError):
        await device_breakdown(session, hid, T0, T0)
