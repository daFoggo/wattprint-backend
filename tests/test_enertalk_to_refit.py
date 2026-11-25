import pandas as pd

from scripts.enertalk_to_refit import to_refit


def _series(values: list[float], start_ms: int = 1_473_120_000_000) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp": [start_ms + i * 5_000 for i in range(len(values))],  # 5 s apart
            "active_power": values,
        }
    )


def test_each_device_is_averaged_to_15_s_and_aligned_with_the_total():
    total = _series([300.0] * 6)
    fridge = _series([100.0, 100.0, 100.0, 0.0, 0.0, 0.0])
    out = to_refit({"total": total, "fridge": fridge})
    assert list(out.columns) == ["Time", "Unix", "Aggregate", "Appliance1", "Issues"]
    assert out["Aggregate"].tolist() == [300.0, 300.0]
    assert out["Appliance1"].tolist() == [100.0, 0.0]


def test_issues_flags_appliances_adding_up_to_more_than_the_total():
    out = to_refit({"total": _series([100.0] * 3), "fridge": _series([400.0] * 3)})
    assert out["Issues"].tolist() == [1]


def test_a_device_with_a_gap_keeps_the_gap_as_nan():
    total = _series([300.0] * 6)
    fridge = _series([100.0, 100.0, 100.0], start_ms=1_473_120_000_000)
    out = to_refit({"total": total, "fridge": fridge})
    assert out["Appliance1"].isna().tolist() == [False, True]


def test_time_is_korea_wall_clock_and_unix_reads_that_clock_as_utc():
    # 2016-09-06 00:00:00 UTC is 09:00 in Korea
    out = to_refit({"total": _series([300.0] * 3)})
    assert out["Time"].iloc[0] == pd.Timestamp("2016-09-06 09:00:00")
    assert out["Unix"].iloc[0] == int(pd.Timestamp("2016-09-06 09:00:00", tz="UTC").timestamp())


def test_two_days_sharing_a_15_s_bin_give_one_row_with_the_mean():
    from scripts.enertalk_to_refit import join_days

    end_of_day_1 = to_refit({"total": _series([100.0] * 3)})  # one bin
    start_of_day_2 = to_refit({"total": _series([300.0] * 3)})  # the same bin, other values
    out = join_days([end_of_day_1, start_of_day_2])
    assert len(out) == 1
    assert out["Aggregate"].tolist() == [200.0]
