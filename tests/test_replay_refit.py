from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd

from scripts import refit


def _frame(walls: list[str], watts: list[float], issues: list[int]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "wall": pd.to_datetime(walls).to_numpy(),
            "watts": np.array(watts, dtype=np.float32),
            "quality": np.array(issues, dtype=np.int16),
        }
    )


def test_db_time_keeps_the_uk_wall_clock_on_vietnam_time():
    # 19:00 UK wall clock, one 52-week year later, is 19:00 in Hanoi (12:00 UTC), same weekday.
    wall = pd.DatetimeIndex(["2014-06-10 19:00:00"])
    ts = refit.db_time(wall, refit.YEAR_DAYS)[0]
    assert ts == pd.Timestamp("2015-06-09 12:00:00", tz=UTC)
    assert ts.tz_convert(refit.HOME_TZ).hour == 19
    assert ts.tz_convert(refit.HOME_TZ).day_of_week == wall[0].day_of_week


def test_pick_shift_puts_the_history_start_inside_the_recording_in_whole_years():
    first = datetime(2013, 9, 17)
    now = datetime(2026, 11, 17, 12, tzinfo=UTC)
    days = refit.pick_shift(first, now, timedelta(days=90))
    assert days % refit.YEAR_DAYS == 0
    start_wall = pd.Timestamp(now).tz_convert(refit.HOME_TZ).tz_localize(None) - timedelta(days=90)
    assert pd.Timestamp(first) + timedelta(days=days) <= start_wall
    assert pd.Timestamp(first) + timedelta(days=days + refit.YEAR_DAYS) > start_wall


def test_shift_for_adds_whole_weeks_only_past_the_end():
    last = datetime(2015, 5, 1)
    inside = refit.db_time(pd.DatetimeIndex([last]), 364)[0].to_pydatetime()
    assert refit.shift_for(inside, 364, last) == 364
    assert refit.shift_for(inside + timedelta(seconds=1), 364, last) == 364 + 7
    assert refit.shift_for(inside + timedelta(days=8), 364, last) == 364 + 14


def test_rows_between_is_half_open_skips_nan_and_flags_issues():
    df = _frame(
        ["2014-01-01 10:00:00", "2014-01-01 10:00:07", "2014-01-01 10:00:14"],
        [100.0, float("nan"), 300.0],
        [0, 0, 1],
    )
    t0 = refit.db_time(df["wall"].iloc[:1], 0)[0].to_pydatetime()
    rows = refit.rows_between(df, t0 - timedelta(seconds=1), t0 + timedelta(seconds=14), 0)
    assert [r.value for r in rows] == [100.0, 300.0]
    assert [r.quality for r in rows] == [0, 1]
    assert {r.channel for r in rows} == {"Aggregate"}
    assert rows[0].ts == t0
    assert refit.rows_between(df, t0, t0 + timedelta(seconds=13), 0) == []  # (lo, hi]
