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


def test_shift_for_plays_the_whole_recording_again_past_its_end():
    first, last = datetime(2015, 2, 2), datetime(2015, 5, 1)  # 88 days: loops every 84, no hole
    inside = refit.db_time(pd.DatetimeIndex([last]), 364)[0].to_pydatetime()
    assert refit.shift_for(inside, 364, first, last) == 364
    assert refit.shift_for(inside + timedelta(seconds=1), 364, first, last) == 364 + 84
    assert refit.shift_for(inside + timedelta(days=85), 364, first, last) == 364 + 168


def test_a_looped_recording_keeps_the_weekday_and_replays_from_near_its_start():
    first, last = datetime(2015, 2, 2, 8), datetime(2015, 5, 1)  # a Monday; loops every 84 days
    start = refit.db_time(pd.DatetimeIndex([first]), 364)[0].to_pydatetime()
    after = start + timedelta(days=84 + 9)  # past the end (88 days), into the second pass
    shift = refit.shift_for(after, 364, first, last)
    wall = pd.Timestamp(after).tz_convert(refit.HOME_TZ).tz_localize(None) - timedelta(days=shift)
    assert wall.day_of_week == (first + timedelta(days=9)).weekday()
    assert first <= wall < first + timedelta(days=10)


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


def test_the_replay_takes_the_aggregate_only_never_a_device_channel(tmp_path):
    # Device figures come only from NILM (rules/data.md): the demo meter never carries REFIT's
    # appliance channels.
    csv = tmp_path / "CLEAN_House9.csv"
    csv.write_text(
        "Time,Unix,Aggregate,Appliance1,Appliance2,Issues\n"
        "2014-01-01 00:00:00,1388534400,500,120,80,0\n"
        "2014-01-01 00:00:08,1388534408,510,125,0,1\n"
    )
    out = refit.load(csv)
    assert list(out.columns) == ["wall", "watts", "quality"]
    assert out["watts"].tolist() == [500, 510]
    assert out["quality"].tolist() == [0, 1]


def test_loop_shifts_lists_each_pass_of_the_recording_until_a_date():
    first, last = datetime(2015, 2, 2), datetime(2015, 5, 1)  # period 84 days
    start = refit.db_time(pd.DatetimeIndex([first]), 364)[0].to_pydatetime()
    assert refit.loop_shifts(first, last, 364, start) == [364]
    assert refit.loop_shifts(first, last, 364, start + timedelta(days=84)) == [364, 448]
    assert refit.loop_shifts(first, last, 364, start + timedelta(days=200)) == [364, 448, 532]
