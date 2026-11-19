"""REFIT recordings as live Vietnamese homes: shared by seed_demo_homes.py and replay_refit.py.

The CSV's `Time` column is UTC (it equals `Unix` on every row, no summer time), and the NILM models
learned their time features from it (dataset/training/data.py, train_house.py). Each sample's UTC
clock time is moved by whole 52-week years and read as Asia/Ho_Chi_Minh time, so a 7 pm dinner
(UK winter) shows at 7 pm in Vietnam (6 pm in UK summer), the weekday is kept, the month drifts at
most ~1.25 days per year shifted, and the NILM worker, which takes time features on the home's
clock, sees what the model was trained on. The database still stores UTC (timestamptz).
"""

import math
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from app.modules.ops.api import ReadingRow

SOURCE_TZ = "UTC"  # the clock of the CSV's `Time`, which the models were trained on
HOME_TZ = "Asia/Ho_Chi_Minh"  # tb_home.timezone is CHECKed to this
YEAR_DAYS = 364  # 52 weeks
WEEK = timedelta(days=7)
CHANNEL = "Aggregate"  # demo homes have the main meter only, like a real home
SEGMENT = "demo"  # etl.tb_watermark.segment of the demo homes


def source(house: int) -> str:
    return f"refit/CLEAN_House{house}.csv"


def meter(house: int) -> str:
    return f"REFIT-H{house}"


def house_of(source_name: str) -> int:
    return int(source_name.removeprefix("refit/CLEAN_House").removesuffix(".csv"))


def load(path: Path) -> pd.DataFrame:
    """Aggregate W, Issues flag and UK wall-clock time (naive), sorted by wall clock."""
    df = pd.read_csv(path, usecols=["Unix", "Aggregate", "Issues"], dtype={"Aggregate": "float32"})
    wall = pd.to_datetime(df["Unix"], unit="s", utc=True).dt.tz_convert(SOURCE_TZ)
    out = pd.DataFrame(
        {
            "wall": wall.dt.tz_localize(None).to_numpy(),
            "watts": df["Aggregate"].to_numpy(),
            "quality": (df["Issues"] == 1).astype("int16").to_numpy(),
        }
    )
    return out.sort_values("wall", kind="stable").reset_index(drop=True)


def _local(ts: datetime) -> pd.Timestamp:
    return pd.Timestamp(ts).tz_convert(HOME_TZ).tz_localize(None)


def db_time(wall: pd.Series | pd.DatetimeIndex, shift_days: int) -> pd.DatetimeIndex:
    shifted = pd.DatetimeIndex(wall) + pd.Timedelta(days=shift_days)
    return shifted.tz_localize(HOME_TZ).tz_convert(UTC)


def pick_shift(first_wall: datetime, now: datetime, history: timedelta) -> int:
    """Whole 52-week years putting `now - history` as late as possible inside the recording."""
    target = _local(now) - history
    years = math.floor((target - pd.Timestamp(first_wall)) / pd.Timedelta(days=YEAR_DAYS))
    return max(years, 0) * YEAR_DAYS


def shift_for(db_hi: datetime, shift_days: int, last_wall: datetime) -> int:
    """Past the end of the recording, add whole weeks so db_hi lands inside it again."""
    wall_hi = _local(db_hi) - pd.Timedelta(days=shift_days)
    weeks = max(0, math.ceil((wall_hi - pd.Timestamp(last_wall)) / WEEK))
    return shift_days + 7 * weeks


def rows_between(df: pd.DataFrame, lo: datetime, hi: datetime, shift_days: int) -> list[ReadingRow]:
    """Aggregate readings whose database time is in (lo, hi]; NaN cells are recording gaps."""
    wall = df["wall"].to_numpy()
    a = np.searchsorted(wall, (_local(lo) - pd.Timedelta(days=shift_days)).to_datetime64(), "right")
    b = np.searchsorted(wall, (_local(hi) - pd.Timedelta(days=shift_days)).to_datetime64(), "right")
    part = df.iloc[a:b]
    part = part[part["watts"].notna()]
    ts = db_time(part["wall"].to_numpy(), shift_days)
    return [
        ReadingRow(when.to_pydatetime(), CHANNEL, float(w), int(q))
        for when, w, q in zip(ts, part["watts"].to_numpy(), part["quality"].to_numpy(), strict=True)
    ]
