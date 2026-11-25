"""ENERTALK (Korea, 15 Hz, CC0) -> the REFIT-style CSV that training/train_house.py reads.

    uv run --with pyarrow python scripts/enertalk_to_refit.py --house 5 --dir <dir>
    ->  dataset/CLEAN_House205.csv

Each device's active power is averaged to 15 s. Columns: Time (Korea clock), Unix, Aggregate (W),
Appliance1..k (W, order of DEVICES), Issues (the appliances add up to more than the total by over
100 W). House N becomes house 200 + N.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEVICES = {  # file name after the number -> trainer label
    "fridge": "Fridge",
    "kimchi-fridge": "Kimchi",
    "washing-machine": "WashMach",
    "rice-cooker": "RiceCooker",
    "microwave": "Microwave",
    "tv": "TV",
}
KOREA = pd.Timedelta(hours=9)  # the files are UTC; the models learn the home's own clock
EXCESS_W = 100  # shortcut: one fixed margin, per-device meter error is not modelled


def _per_15s(df: pd.DataFrame) -> pd.Series:
    index = pd.to_datetime(df["timestamp"], unit="ms") + KOREA
    return df["active_power"].set_axis(index).resample("15s").mean()


def to_refit(frames: dict[str, pd.DataFrame], names: list[str] | None = None) -> pd.DataFrame:
    """frames: 'total' plus device names (keys of DEVICES), each with timestamp (ms), active_power.
    names: the house's devices in column order; a day without one leaves its column NaN."""
    out = pd.DataFrame({"Aggregate": _per_15s(frames["total"])})
    names = names or [d for d in DEVICES if d in frames]
    for i, d in enumerate(names, 1):
        out[f"Appliance{i}"] = _per_15s(frames[d]) if d in frames else float("nan")
    apps = out.drop(columns="Aggregate")
    out["Issues"] = (apps.sum(axis=1) > out["Aggregate"] + EXCESS_W).astype(int)
    out.index.name = "Time"
    out = out.dropna(subset=["Aggregate"]).reset_index()
    # Unix: the local clock read as UTC, as in REFIT where Time == Unix (scripts/refit.py shifts it)
    out.insert(1, "Unix", (out["Time"] - pd.Timestamp(0)) // pd.Timedelta(seconds=1))
    return out


def join_days(parts: list[pd.DataFrame]) -> pd.DataFrame:
    """Days are resampled alone, so a bin at midnight can come from two files: average them."""
    out = pd.concat(parts, ignore_index=True)
    out = out.groupby("Time", as_index=False).agg(
        {**{c: "mean" for c in out.columns if c not in ("Time", "Issues")}, "Issues": "max"}
    )
    out["Unix"] = (out["Time"] - pd.Timestamp(0)) // pd.Timedelta(seconds=1)
    return out


def main(house: int, folder: Path) -> None:
    days = sorted(p for p in (folder / f"{house:02d}").iterdir() if p.is_dir())
    files = [
        (day, f.name.split(".")[0].split("_", 1)[1], f)
        for day in days
        for f in day.glob("*.parquet.gzip")
    ]
    names = [d for d in DEVICES if any(n == d for _, n, _ in files)]
    parts = []
    for day in days:
        frames = {
            n: pd.read_parquet(f) for d, n, f in files if d == day and (n == "total" or n in names)
        }
        if "total" in frames:
            parts.append(to_refit(frames, names))
    print("devices:", names)
    out = join_days(parts)
    path = ROOT / "dataset" / f"CLEAN_House{200 + house}.csv"
    out.to_csv(path, index=False)
    print(path, len(out), list(out.columns))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--house", type=int, required=True)
    ap.add_argument("--dir", type=Path, required=True)
    a = ap.parse_args()
    main(a.house, a.dir)
