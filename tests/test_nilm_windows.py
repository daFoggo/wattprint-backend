from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd

from app.modules.nilm.services import windows

T0 = datetime(2026, 11, 1, tzinfo=UTC)


def idx(n: int, start: datetime = T0) -> pd.DatetimeIndex:
    return pd.date_range(start, periods=n, freq=windows.STEP)


def test_grid_averages_samples_per_15s_bin_on_the_epoch():
    ts = pd.DatetimeIndex([T0 + timedelta(seconds=s) for s in (1, 8, 16, 47)])
    g = windows.grid(ts, np.array([100.0, 300.0, 50.0, 70.0]))
    assert list(g.index) == list(idx(4))
    assert g.iloc[0] == 200.0 and g.iloc[1] == 50.0 and np.isnan(g.iloc[2]) and g.iloc[3] == 70.0


def test_fill_short_gaps_carries_runs_up_to_the_limit_only():
    s = pd.Series([1.0, np.nan, np.nan, 2.0, *[np.nan] * 5, 3.0], index=idx(10))
    out = windows.fill_short_gaps(s, max_bins=4)
    assert out.iloc[1:3].tolist() == [1.0, 1.0]  # 2-bin gap filled
    assert out.iloc[4:9].isna().all()  # 5-bin gap left alone, not partly filled
    lead = windows.fill_short_gaps(pd.Series([np.nan, 1.0], index=idx(2)))
    assert np.isnan(lead.iloc[0])  # nothing to carry into a leading gap


def test_window_starts_cover_every_bin_of_long_runs_and_skip_short_runs():
    valid = np.r_[np.ones(50, bool), np.zeros(3, bool), np.ones(10, bool), np.ones(0, bool)]
    valid = np.r_[valid, np.zeros(2, bool), np.ones(37, bool)]
    starts = windows.window_starts(idx(len(valid)), valid, window=16, stride=8, open_head=False)
    covered = np.zeros(len(valid), bool)
    for a in starts:
        assert valid[a : a + 16].all() and a + 16 <= len(valid)
        covered[a : a + 16] = True
    long_runs = np.r_[np.ones(50, bool), np.zeros(15, bool), np.ones(37, bool)]
    assert (covered == long_runs).all()  # the 10-bin run is shorter than a window: no estimate


def test_window_starts_sit_on_a_global_grid_whatever_the_slice():
    valid = np.ones(200, bool)
    full = windows.window_starts(idx(200), valid, 16, 8, open_head=False)
    later = windows.window_starts(idx(150, T0 + 50 * windows.STEP), valid[50:], 16, 8, True)
    grid_full = {a for a in full if a >= 50 and a + 16 < 200}
    grid_later = {a + 50 for a in later if a + 50 + 16 < 200}
    assert grid_full == grid_later  # no head window when the run goes on before the slice


def test_balance_scales_appliances_into_the_aggregate():
    agg = np.array([100.0, 100.0, 0.0, -5.0])
    apps = np.array([[30.0, 90.0, 10.0, 1.0], [20.0, 60.0, 0.0, 1.0]])
    out, other = windows.balance(agg, apps)
    assert np.allclose(out.sum(0) + other, np.clip(agg, 0, None))
    assert np.allclose(out[:, 0], [30.0, 20.0]) and other[0] == 50.0  # under the aggregate: kept
    assert np.allclose(out[:, 1], [60.0, 40.0]) and other[1] == 0.0  # over: scaled by 100/150
    assert (out >= 0).all() and (other >= 0).all()


def test_time_features_follow_the_home_clock():
    feats = windows.time_features(pd.DatetimeIndex([T0]), "Asia/Ho_Chi_Minh")  # 07:00 local
    hour = np.degrees(np.arctan2(feats[2, 0], feats[3, 0])) / 15
    assert round(hour) == 7


def test_plan_marks_bins_final_once_every_covering_window_is_inside_the_data():
    n, w = 100, 16
    ts = idx(n)
    p = windows.plan(ts, np.full(n, 500.0), T0 + 20 * windows.STEP, w, w // 2, open_head=False)
    assert p.write_from == 20
    assert p.final_until == (ts[-1] - (w - 1) * windows.STEP).to_pydatetime()
    young = windows.plan(ts[:10], np.full(10, 5.0), T0, w, w // 2, open_head=False)
    assert young.final_until is None and young.starts == []


def test_model_inputs_clip_the_aggregate_as_the_training_data_was():
    s = pd.Series([3.0, 5.0, 2500.0, 12_000.0], index=idx(4))
    x = windows.model_inputs(s, [0], 4, "Asia/Ho_Chi_Minh")
    assert x[0, 0].tolist() == [0.0, 5.0, 2500.0, 10_000.0]
