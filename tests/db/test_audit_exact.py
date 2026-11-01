import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from tests.audit.exact import compare, exact_days, median_cadence, percentile

D0 = datetime(2026, 3, 1, 17, tzinfo=UTC)  # local midnight of 2026-03-02


async def _series(conn):
    home = uuid.uuid4()
    await conn.execute(text("INSERT INTO core.home (id, name) VALUES (:i, 'X')"), {"i": home})
    return await conn.scalar(
        text(
            "INSERT INTO energy.series (home_id, kind, metric, unit) "
            "VALUES (:h, 'main', 'power_w', 'W') RETURNING series_id"
        ),
        {"h": home},
    )


async def _put(conn, sid, rows):
    for ts, value, q in rows:
        await conn.execute(
            text("INSERT INTO energy.reading (ts, series_id, value, quality) VALUES (:t,:s,:v,:q)"),
            {"t": ts, "s": sid, "v": value, "q": q},
        )


async def test_exact_zero_order_hold_with_gap_cap_and_flagged_rows(conn):
    sid = await _series(conn)
    # 10 s cadence of 360 W for the first hour: 360 W * 3600 s / 3600 = 360 Wh
    rows = [(D0 + timedelta(seconds=10 * i), 360.0, 0) for i in range(360)]
    # then a 2 h hole (> 5 x cadence): the last sample of the hour holds only 50 s, the sample
    # after the hole starts a new hold of 100 W for 30 s (3 samples x 10 s)
    after = D0 + timedelta(hours=3)
    rows += [(after + timedelta(seconds=10 * i), 100.0, 0) for i in range(3)]
    # a flagged sample never contributes (but still ends the hold of the previous one)
    rows += [(after + timedelta(seconds=30), 9999.0, 1)]
    await _put(conn, sid, rows)
    cadence = await median_cadence(conn, sid)
    assert cadence == 10.0
    days = await exact_days(conn, sid, cadence)
    assert list(days) == [D0]
    wh, minutes = days[D0]
    # 359 holds of 10 s + the last sample capped at 50 s, then 3 holds of 10 s at 100 W
    expected = (360.0 * (359 * 10 + 50) + 100.0 * 30) / 3600
    assert abs(wh - expected) < 1e-6
    assert minutes == 60 + 1  # 60 minutes of the first hour + the minute after the hole


def test_percentile_and_compare():
    assert percentile([], 50) is None
    assert percentile([1.0, 3.0], 50) == 2.0
    d1, d2 = D0, D0 + timedelta(days=1)
    exact = {d1: (1000.0, 1440), d2: (1000.0, 600)}
    view = {d1: (1005.0, 1440, 1), d2: (400.0, 600, 1)}
    res = compare(exact, view)
    assert res["full_coverage"]["days"] == 1
    assert res["full_coverage"]["err_pct_max"] == 0.5
    assert res["full_coverage"]["days_over_gate"] == 0
    assert res["low_coverage"]["days"] == 1 and res["low_coverage"]["days_over_gate"] == 1
    assert res["covered_minutes_mismatch_days"] == 0
