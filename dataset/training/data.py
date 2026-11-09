"""Cut REFIT House 2 into fixed-length windows for NILM training.

Readings are resampled to 15 s; windows never cross gaps (missing aggregate) and are cut
from the start of each continuous run, so a window of L = 128·k covers exactly the k
consecutive 128-step windows that start at the same time.

    python dataset/training/data.py                    # 128 steps (32 min) -> refit_house2_windows.npz
    python dataset/training/data.py --window 256 512   # -> refit_house2_windows_L256.npz, _L512.npz
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

WINDOW_SIZE = 128
SAMPLE_PERIOD = pd.Timedelta(seconds=15)
TIME_FEATURE_NAMES = ["minute_sin", "minute_cos", "hour_sin", "hour_cos",
                      "weekday_sin", "weekday_cos", "month_sin", "month_cos"]

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCES = [
    ROOT / "preprocessed" / "refit_house2_before_gap.csv",
    ROOT / "preprocessed" / "refit_house2_after_gap.csv",
]
DEFAULT_OUTPUT = ROOT / "training" / "data"


def output_name(window: int) -> str:
    return "refit_house2_windows.npz" if window == WINDOW_SIZE else f"refit_house2_windows_L{window}.npz"


def time_features(index: pd.DatetimeIndex) -> np.ndarray:
    minute = index.minute.to_numpy(dtype=np.float64)
    hour = index.hour.to_numpy(dtype=np.float64)
    weekday = index.day_of_week.to_numpy(dtype=np.float64)
    month = index.month.to_numpy(dtype=np.float64) - 1

    values = []
    for value, period in ((minute, 60), (hour, 24), (weekday, 7), (month, 12)):
        angle = 2 * np.pi * value / period
        values.extend((np.sin(angle), np.cos(angle)))
    return np.asarray(values, dtype=np.float32)


def appliance_columns(frame: pd.DataFrame) -> list[str]:
    return [c for c in frame.columns if c.startswith("Appliance")]


def load_resampled(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, parse_dates=["Time"], index_col="Time").sort_index()
    return frame[["Aggregate", *appliance_columns(frame)]].resample(SAMPLE_PERIOD).mean()


def clip_power(values: np.ndarray) -> np.ndarray:
    return np.clip(values, 0.0, None)


def window_indices(valid: np.ndarray, window: int) -> np.ndarray:
    """(N, window) indices of non-overlapping windows inside each continuous valid run."""
    edges = np.diff(np.r_[0, valid.astype(np.int8), 0])
    run_starts, run_ends = np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)
    starts = [s + k * window
              for s, e in zip(run_starts, run_ends) for k in range((e - s) // window)]
    return np.asarray(starts, dtype=np.int64)[:, None] + np.arange(window)


def make_windows(frame: pd.DataFrame, window: int) -> dict[str, np.ndarray]:
    aggregate = clip_power(frame["Aggregate"].to_numpy(np.float32))                 # (T,)
    targets = clip_power(frame[appliance_columns(frame)].to_numpy(np.float32).T)    # (C, T)
    features = time_features(frame.index)                                           # (8, T)

    ids = window_indices(np.isfinite(aggregate), window)                            # (N, L)
    return {"aggregate": aggregate[ids],                                            # (N, L)
            "targets": targets[:, ids].transpose(1, 0, 2),                          # (N, C, L)
            "time_features": features[:, ids].transpose(1, 0, 2),                   # (N, 8, L)
            "window_start": frame.index[ids[:, 0]].to_numpy("datetime64[ns]")}


def prepare(sources: list[Path], output: Path, windows: list[int]) -> list[Path]:
    frames = [load_resampled(path) for path in sources]
    written = []
    for window in windows:
        parts = [make_windows(frame, window) for frame in frames]
        for path, part in zip(sources, parts):
            print(f"[L={window}] {path.name}: {len(part['aggregate']):,} windows")
        arrays = {k: np.concatenate([p[k] for p in parts]) for k in parts[0]}
        output.mkdir(parents=True, exist_ok=True)
        destination = output / output_name(window)
        np.savez_compressed(destination, **arrays,
                            appliance_names=np.asarray(appliance_columns(frames[0])),
                            time_feature_names=np.asarray(TIME_FEATURE_NAMES),
                            sample_seconds=np.int64(SAMPLE_PERIOD.total_seconds()),
                            window=np.int64(window))
        print(f"[L={window}] saved {len(arrays['aggregate']):,} windows -> {destination}")
        written.append(destination)
    return written


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--window", type=int, nargs="+", default=[WINDOW_SIZE],
                        help="window length(s) in 15 s steps (multiples of 128 recommended)")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    prepare(DEFAULT_SOURCES, args.output, args.window)
