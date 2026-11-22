"""Self-contained REFIT preprocessing matching train_house.load."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

CHANNELS = {
    2: {"Fridge": "Appliance1", "WashMach": "Appliance2", "Dishwash": "Appliance3",
        "Microwave": "Appliance5", "Toaster": "Appliance6", "Kettle": "Appliance8"},
    3: {"Fridge": "Appliance2", "WashMach": "Appliance6", "Dishwash": "Appliance5",
        "Microwave": "Appliance8", "Toaster": "Appliance1", "Kettle": "Appliance9"},
    5: {"Fridge": "Appliance1", "WashMach": "Appliance3", "Dishwash": "Appliance4",
        "Microwave": "Appliance7", "Toaster": "Appliance9", "Kettle": "Appliance8"},
    6: {"Freezer": "Appliance1", "WashMach": "Appliance2", "Dishwash": "Appliance3",
        "Microwave": "Appliance6", "Toaster": "Appliance8", "Kettle": "Appliance7"},
}
SAMPLE_SECONDS, WINDOW, MIN_W, MAX_W = 15, 256, 5, 10_000


def time_features(index: pd.DatetimeIndex) -> np.ndarray:
    features = []
    for values, period in ((index.minute, 60), (index.hour, 24),
                           (index.day_of_week, 7), (index.month - 1, 12)):
        angle = 2 * np.pi * np.asarray(values, dtype=np.float64) / period
        features.extend((np.sin(angle), np.cos(angle)))
    return np.asarray(features, dtype=np.float32)


def load_house(csv_path: str | Path, house: int) -> tuple[np.ndarray, np.ndarray, pd.DatetimeIndex, pd.DatetimeIndex]:
    """Return contiguous windows: x (N,9,256), y (N,C,256), start/end timestamps."""
    if house not in CHANNELS:
        raise ValueError(f"unsupported REFIT house {house}")
    channels = list(CHANNELS[house].values())
    cols = ["Aggregate", *channels]
    frame = pd.read_csv(csv_path, usecols=["Time", *cols, "Issues"])
    frame = frame.loc[frame["Issues"] != 1]
    values = frame[cols]
    frame[cols] = values.clip(upper=MAX_W).mask(values.notna() & (values < MIN_W), 0)
    frame = frame.assign(Time=pd.to_datetime(frame["Time"])).set_index("Time")[cols].sort_index()
    frame = frame.resample(f"{SAMPLE_SECONDS}s").mean()
    finite = np.isfinite(frame.to_numpy()).all(axis=1)
    edges = np.diff(np.r_[0, finite.astype(np.int8), 0])
    starts = [
        start + offset * WINDOW
        for start, end in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1), strict=True)
        for offset in range((end - start) // WINDOW)
    ]
    ids = np.asarray(starts, dtype=np.int64)[:, None] + np.arange(WINDOW)
    aggregate = frame["Aggregate"].to_numpy(np.float32)
    y = frame[channels].to_numpy(np.float32).T
    x = np.concatenate([
        aggregate[ids][:, None], time_features(frame.index)[..., ids].transpose(1, 0, 2)
    ], axis=1).astype(np.float32)
    y = np.ascontiguousarray(y[:, ids].transpose(1, 0, 2))
    return x, y, frame.index[ids[:, 0]], frame.index[ids[:, -1]]
