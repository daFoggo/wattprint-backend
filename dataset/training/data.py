"""Prepare REFIT sequences for NILMFormer.

Each source CSV is treated as a continuous segment. Windows never cross CSV
boundaries, missing timestamps, or non-15-second intervals.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

WINDOW_SIZE = 128
SAMPLE_PERIOD = pd.Timedelta(seconds=15)
TAU_MAX_WATTS = 10_000.0
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCES = [
    ROOT / "preprocessed" / "refit_house2_before_gap.csv",
    ROOT / "preprocessed" / "refit_house2_after_gap.csv",
]
DEFAULT_OUTPUT = ROOT / "training" / "data"


def time_features(index: pd.DatetimeIndex) -> np.ndarray:
    """Return cyclical minute/hour/weekday/month features as (8, time)."""
    minute = index.minute.to_numpy(dtype=np.float64)
    hour = index.hour.to_numpy(dtype=np.float64)
    weekday = index.day_of_week.to_numpy(dtype=np.float64)
    month = (index.month.to_numpy(dtype=np.float64) - 1)
    values = []
    for value, period in ((minute, 60), (hour, 24), (weekday, 7), (month, 12)):
        angle = 2 * np.pi * value / period
        values.extend((np.sin(angle), np.cos(angle)))
    return np.asarray(values, dtype=np.float32)


def make_windows(frame: pd.DataFrame, source: str) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    required = {"Time", "Aggregate"}
    if not required.issubset(frame.columns):
        raise ValueError(f"{source}: required columns are Time and Aggregate")
    frame = frame.copy()
    frame["Time"] = pd.to_datetime(frame["Time"], errors="coerce")
    frame["Aggregate"] = pd.to_numeric(frame["Aggregate"], errors="coerce")
    frame = frame.dropna(subset=["Time", "Aggregate"]).sort_values("Time")
    if frame["Time"].duplicated().any():
        raise ValueError(f"{source}: duplicate timestamps found")
    appliance_cols = [c for c in frame.columns if c.startswith("Appliance")]
    for col in appliance_cols:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")

    # REFIT readings are irregular (often 1–15 seconds apart). Bin them to
    # the intended 15-second cadence before windowing; empty bins stay gaps.
    frame = frame.set_index("Time")
    numeric_cols = ["Aggregate", *appliance_cols]
    frame = frame[numeric_cols].resample(SAMPLE_PERIOD).mean()
    # Normalize datetime resolution: Pandas 4 may expose datetime64[us], while
    # Timedelta.value is nanoseconds.
    times = pd.DatetimeIndex(frame.index).as_unit("ns")
    aggregate = frame["Aggregate"].to_numpy(dtype=np.float32)
    features = time_features(times)
    targets = frame[appliance_cols].to_numpy(dtype=np.float32) if appliance_cols else np.empty((len(frame), 0), dtype=np.float32)

    xs, ys, starts, raw_power = [], [], [], []
    # Break at sampling gaps, then discard each segment's incomplete tail.
    valid = np.isfinite(aggregate)
    continuous = valid.copy()
    if len(times) > 1:
        continuous[1:] &= np.diff(times.asi8) == SAMPLE_PERIOD.value
    run_starts = np.flatnonzero(continuous & ~np.r_[False, continuous[:-1]])
    run_ends = np.flatnonzero(continuous & ~np.r_[continuous[1:], False]) + 1
    for start, end in zip(run_starts, run_ends):
        segment = np.arange(start, end)
        count = len(segment) // WINDOW_SIZE
        for offset in range(count):
            ids = segment[offset * WINDOW_SIZE : (offset + 1) * WINDOW_SIZE]
            xs.append(np.concatenate((aggregate[ids][None, :], features[:, ids]), axis=0))
            # Match model input convention: (channels, sequence length).
            ys.append(targets[ids].T)
            starts.append(times[ids[0]].to_datetime64())
            raw_power.append(np.concatenate((aggregate[ids][None, :], targets[ids].T), axis=0))
    if not xs:
        return (np.empty((0, 9, WINDOW_SIZE), np.float32),
                np.empty((0, len(appliance_cols), WINDOW_SIZE), np.float32),
                np.empty((0,), dtype="datetime64[ns]"), np.empty((0, 10, WINDOW_SIZE), np.float32))
    return np.stack(xs), np.stack(ys), np.asarray(starts, dtype="datetime64[ns]"), np.stack(raw_power)


def prepare(sources: list[Path], output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    all_x, all_y, all_starts, all_power = [], [], [], []
    appliance_names: np.ndarray | None = None
    for path in sources:
        frame = pd.read_csv(path)
        x, y, starts, power = make_windows(frame, str(path))
        names = np.asarray([c for c in frame.columns if c.startswith("Appliance")])
        if appliance_names is None:
            appliance_names = names
        elif not np.array_equal(appliance_names, names):
            raise ValueError("All source files must have the same appliance columns in the same order")
        all_x.append(x)
        all_y.append(y)
        all_starts.append(starts)
        all_power.append(power)
        print(f"{path.name}: processed {len(x):,} windows")

    raw_power = np.concatenate(all_power, axis=0)
    tau_max = TAU_MAX_WATTS
    power_scaled = np.clip(raw_power, 0.0, tau_max) / tau_max
    x = np.concatenate((power_scaled[:, :1], np.concatenate(all_x, axis=0)[:, 1:]), axis=1)
    y = power_scaled[:, 1:]
    starts = np.concatenate(all_starts, axis=0)
    destination = output / "refit_house2_windows.npz"
    np.savez_compressed(destination, x=x, y=y, window_start=starts, tau_max=np.float32(tau_max),
                        appliance_names=appliance_names if appliance_names is not None else np.array([]))
    print(f"Saved {len(x):,} combined windows, x={x.shape}, y={y.shape} -> {destination}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", nargs="+", type=Path, default=DEFAULT_SOURCES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    prepare(args.sources, args.output)


if __name__ == "__main__":
    main()
