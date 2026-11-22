from datetime import UTC, date, datetime, timedelta

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import text

from app.database import SessionLocal, engine
from app.modules.energy.api import backfill_aggregates
from app.modules.expect.services import calendar
from app.modules.expect.services.features import (
    FEATURES,
    base_frame,
    calendar_frame,
    hourly_actual,
    presence_frame,
)
from scripts import refit

TZ = "Asia/Ho_Chi_Minh"
NOW = pd.Timestamp("2026-11-21 05:00", tz=UTC)  # 12:00 in Hanoi, a Saturday


def hours(start: pd.Timestamp, n: int) -> pd.DatetimeIndex:
    return pd.date_range(start, periods=n, freq="h")


def test_presence_is_routine_not_the_hour_itself():
    history = hours(NOW - pd.Timedelta(days=35), 35 * 24)
    active = pd.Series(False, index=history)
    target = NOW - pd.Timedelta(hours=2)
    for k in (1, 2):  # active at this weekday-hour one and two weeks before, not three or four
        active[target - pd.Timedelta(days=7 * k)] = True
    active[target] = True  # the hour's own activity must not count
    got = presence_frame(active, pd.DatetimeIndex([target]), NOW)
    assert got[target] == pytest.approx(0.5)


def test_presence_of_future_hours_follows_the_routine():
    history = hours(NOW - pd.Timedelta(days=35), 35 * 24)
    active = pd.Series(False, index=history)
    t = NOW + pd.Timedelta(days=10)
    for k in range(1, 6):
        active[t - pd.Timedelta(days=7 * (k + 1))] = True  # the same weekday-hour every week
    got = presence_frame(active, pd.DatetimeIndex([t]), NOW)
    assert got[t] == pytest.approx(1.0)


def test_source_date_and_christmas_are_holidays():
    assert calendar.source_date(date(2026, 12, 10), 4368) == date(2014, 12, 25)
    assert calendar.is_holiday(date(2014, 12, 25))
    assert calendar.is_holiday(date(2014, 12, 31))  # the Christmas week
    assert calendar.is_holiday(date(2014, 8, 25))  # summer bank holiday
    assert not calendar.is_holiday(date(2014, 9, 10))


def test_calendar_columns_use_the_home_clock_and_the_recording_date():
    idx = pd.DatetimeIndex([pd.Timestamp("2026-12-10 03:00", tz=UTC)])  # 10:00 in Hanoi, Thursday
    cal = calendar_frame(idx, TZ, 4368)
    assert cal.iloc[0].tolist() == [10, 3, 1]
    assert calendar_frame(idx, TZ, None).iloc[0]["holiday"] == 0


def test_demo_meter_serial_matches_the_seed_scripts():
    for house, key in ((2, None), (5, "5-heat")):
        assert calendar.meter_serial(refit.source(house, key)) == refit.meter(house, key)


def test_base_7d_is_held_for_future_rows():
    days = pd.date_range("2026-11-07", "2026-11-20", freq="D").date
    daily = pd.Series([10.0] * 7 + [20.0] * 7, index=days)
    daily[date(2026, 11, 19)] = np.nan  # a partial day does not count
    idx = pd.DatetimeIndex(
        [pd.Timestamp("2026-11-14 05:00", tz=UTC), NOW, NOW + pd.Timedelta(days=3)]
    )
    got = base_frame(daily, idx, TZ, NOW)
    assert got.iloc[0] == pytest.approx(10.0)  # the 7 days before Nov 14
    assert got.iloc[1] == pytest.approx(20.0)  # Nov 14..20 without the 19th
    assert got.iloc[2] == got.iloc[1]


def test_feature_names_are_unique_and_grouped():
    assert len(FEATURES) == len(set(FEATURES))


@pytest.fixture
async def main_series():
    async with SessionLocal() as s, s.begin():
        hid = await s.scalar(text("INSERT INTO public.tb_home (name) VALUES ('f') RETURNING id"))
        sid = await s.scalar(
            text(
                "INSERT INTO public.tb_series (home_id, kind, metric, unit) "
                "VALUES (:h, 'main', 'power_w', 'W') RETURNING series_id"
            ),
            {"h": hid},
        )
    yield hid, sid
    async with SessionLocal() as s, s.begin():
        await s.execute(text("DELETE FROM public.tb_reading WHERE series_id = :s"), {"s": sid})
        await s.execute(text("DELETE FROM public.tb_home WHERE id = :h"), {"h": hid})


async def test_gap_hours_are_nan_in_actual(main_series):
    hid, sid = main_series
    h0 = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) - timedelta(hours=3)
    rows = [{"t": h0 + timedelta(minutes=m), "v": 1000.0} for m in range(60)]  # a full hour at 1 kW
    rows += [{"t": h0 + timedelta(hours=1, minutes=m), "v": 1000.0} for m in range(20)]  # 20 min
    async with SessionLocal() as s, s.begin():
        await s.execute(
            text("INSERT INTO public.tb_reading (ts, series_id, value) VALUES (:t, :s, :v)"),
            [{**r, "s": sid} for r in rows],
        )
    async with engine.connect() as c:  # rows behind the aggregates' watermark show after a refresh
        c = await c.execution_options(isolation_level="AUTOCOMMIT")
        await backfill_aggregates(c, h0, h0 + timedelta(hours=3))
    async with SessionLocal() as s:
        got = await hourly_actual(s, hid, h0, h0 + timedelta(hours=3))
    assert len(got) == 3
    assert got.iloc[0] == pytest.approx(1.0, rel=0.02)
    assert np.isnan(got.iloc[1]) and np.isnan(got.iloc[2])


async def test_frame_has_every_hour_and_feature(main_series):
    from app.modules.expect.services.features import feature_frame

    hid, _ = main_series
    lo = datetime(2026, 11, 20, tzinfo=UTC)
    async with SessionLocal() as s:
        frame = await feature_frame(s, hid, lo, lo + timedelta(hours=30), NOW.to_pydatetime())
    assert list(frame.columns) == list(FEATURES)
    assert len(frame) == 30
    assert frame["hour"].notna().all() and frame["holiday"].eq(0).all()  # a real home: no REFIT
