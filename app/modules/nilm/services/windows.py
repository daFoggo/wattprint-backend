from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

STEP = pd.Timedelta(seconds=15)  # the model's sample period (dataset/training/data.py)
MAX_FILL_BINS = 4  # gaps up to 60 s are carried forward; REFIT logs ~62 s apart at times
INPUT_CHANNELS = 9  # aggregate + 8 time features
# The training data was clipped so (dataset/scripts/eda.ipynb): under 5 W is 0, over 10 kW is 10 kW.
MIN_W, MAX_W = 5.0, 10_000.0


def grid(ts: pd.DatetimeIndex, watts: np.ndarray) -> pd.Series:
    """Mean power per 15 s bin, bins labelled by their start and aligned to the epoch."""
    s = pd.Series(np.asarray(watts, dtype=np.float64), index=ts).sort_index()
    return s.resample(STEP, origin="epoch").mean()


def fill_short_gaps(s: pd.Series, max_bins: int = MAX_FILL_BINS) -> pd.Series:
    """Carry the last value over NaN runs of at most max_bins; longer runs stay NaN."""
    nan = s.isna().to_numpy()
    if not nan.any():
        return s
    edges = np.diff(np.r_[0, nan.astype(np.int8), 0])
    out = s.to_numpy().copy()
    for a, b in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1), strict=True):
        if a > 0 and b - a <= max_bins:  # a leading gap has nothing to carry
            out[a:b] = out[a - 1]
    return pd.Series(out, index=s.index)


def runs(valid: np.ndarray) -> list[tuple[int, int]]:
    """[start, end) index ranges of consecutive True values."""
    edges = np.diff(np.r_[0, valid.astype(np.int8), 0])
    return list(
        zip(np.flatnonzero(edges == 1).tolist(), np.flatnonzero(edges == -1).tolist(), strict=True)
    )


def window_starts(
    index: pd.DatetimeIndex, valid: np.ndarray, window: int, stride: int, open_head: bool
) -> list[int]:
    """Start positions of the windows to run, deterministic for any slice that holds them.

    Windows sit on a global grid (every `stride` bins since the epoch), so re-reading a different
    slice yields the same windows. A run also gets one window at its start (unless it touches the
    slice head and `open_head` says the data goes on before) and one ending at its last bin, so
    edge bins are covered too. Runs shorter than `window` get none.
    """
    bin_no = index.as_unit("ns").asi8 // STEP.value  # pandas 3 defaults to us: pin ns
    starts: set[int] = set()
    for a, b in runs(valid):
        if b - a < window:
            continue
        first = a + (-bin_no[a]) % stride
        starts.update(range(first, b - window + 1, stride))
        if not (a == 0 and open_head):
            starts.add(a)
        starts.add(b - window)
    return sorted(starts)


def time_features(index: pd.DatetimeIndex, tz: str) -> np.ndarray:
    """(8, L) sin/cos of minute, hour, weekday, month on the home's wall clock (as in training)."""
    local = index.tz_convert(ZoneInfo(tz))
    values = []
    for value, period in (
        (local.minute, 60),
        (local.hour, 24),
        (local.day_of_week, 7),
        (local.month - 1, 12),
    ):
        angle = 2 * np.pi * np.asarray(value, dtype=np.float64) / period
        values.extend((np.sin(angle), np.cos(angle)))
    return np.asarray(values, dtype=np.float32)


def model_inputs(s: pd.Series, starts: list[int], window: int, tz: str) -> np.ndarray:
    """(B, 9, window): aggregate W clipped as in training + time features, one row per window."""
    agg = s.to_numpy(np.float32)
    agg = np.where(agg < MIN_W, 0.0, np.minimum(agg, MAX_W)).astype(np.float32)
    feats = time_features(s.index, tz)
    x = np.empty((len(starts), INPUT_CHANNELS, window), dtype=np.float32)
    for i, a in enumerate(starts):
        x[i, 0] = agg[a : a + window]
        x[i, 1:] = feats[:, a : a + window]
    return x


def merge(n: int, starts: list[int], window: int, appliance_w: np.ndarray) -> np.ndarray:
    """Average overlapping window outputs (B, C, window) into (C, n); uncovered bins are NaN."""
    total = np.zeros((appliance_w.shape[1], n), dtype=np.float64)
    count = np.zeros(n, dtype=np.int32)
    for i, a in enumerate(starts):
        total[:, a : a + window] += appliance_w[i]
        count[a : a + window] += 1
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(count > 0, total / count, np.nan)


def balance(aggregate: np.ndarray, appliances: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Scale appliances down where they exceed the aggregate; Other takes the rest (>= 0).

    Afterwards appliances.sum(0) + other == clip(aggregate, 0) wherever the inputs are finite.
    """
    agg = np.clip(aggregate, 0.0, None)
    apps = np.clip(appliances, 0.0, None)
    total = apps.sum(axis=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        scale = np.where(total > agg, np.where(total > 0, agg / total, 0.0), 1.0)
    apps = apps * scale
    return apps, np.clip(agg - apps.sum(axis=0), 0.0, None)


@dataclass(frozen=True)
class Plan:
    """What one pass over a slice computes and writes."""

    series: pd.Series  # aggregate on the 15 s grid, short gaps filled
    starts: list[int]  # window start positions in `series`
    write_from: int  # first position written (the previous checkpoint)
    final_until: datetime | None  # new checkpoint: every bin before it is final


def plan(
    ts: pd.DatetimeIndex,
    watts: np.ndarray,
    checkpoint: datetime,
    window: int,
    stride: int,
    open_head: bool,
) -> Plan | None:
    """Plan a pass over readings read from `checkpoint - 2 * window` bins onwards.

    A bin is final once every window that could cover it lies inside the data seen, i.e. it is
    at least `window - 1` bins older than the newest bin. Bins from the checkpoint onwards are
    (re)written each pass; the ones not yet final are provisional and the next pass overwrites them.
    """
    if len(ts) == 0:
        return None
    s = fill_short_gaps(grid(ts, watts))
    valid = s.notna().to_numpy()
    starts = window_starts(s.index, valid, window, stride, open_head)
    write_from = int(np.searchsorted(s.index.as_unit("ns").asi8, pd.Timestamp(checkpoint).value))
    newest = s.index[-1]
    final = newest - (window - 1) * STEP
    final_until = final.to_pydatetime() if final > pd.Timestamp(checkpoint) else None
    return Plan(s, starts, write_from, final_until)
