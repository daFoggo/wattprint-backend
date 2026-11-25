"""Plegma (Greece, 10 s, CC BY 4.0) -> the REFIT-style CSV that training/train_house.py reads.

    uv run python scripts/plegma_to_refit.py --house 1  ->  dataset/CLEAN_House101.csv

Columns: Time, Unix, Aggregate (W), Appliance1..k (W, label order of NAMES), Issues (Plegma's
own flag: the appliances add up to more than the aggregate). House N becomes house 100 + N.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PLEGMA = ROOT / "dataset" / "external" / "plegma" / "Clean_Dataset"
ACS = [
    "ac_1",
    "ac_2",
    "ac_3",
]  # the split units of a home add up to one "AC": the app tells devices by type
NAMES = {  # Plegma channel -> trainer label, in the order the trainer sees them
    "ac": "AC",
    "boiler": "Boiler",
    "fridge": "Fridge",
    "washing_machine": "WashMach",
    "dishwasher": "Dishwash",
}


def _with_ac(df: pd.DataFrame) -> pd.DataFrame:
    units = [c for c in ACS if c in df.columns and df[c].notna().any()]
    if not units:
        return df
    return df.assign(
        ac=df[units].sum(axis=1, skipna=False)
    )  # a gap in one unit is a gap in the sum


def _channels(df: pd.DataFrame) -> list[str]:
    return [c for c in NAMES if c in df.columns and df[c].notna().any()]


def LABELS(df: pd.DataFrame) -> dict[str, str]:  # noqa: N802
    """Trainer label -> its CSV column, for the channels this house really has."""
    return {NAMES[c]: f"Appliance{i}" for i, c in enumerate(_channels(_with_ac(df)), 1)}


def to_refit(df: pd.DataFrame) -> pd.DataFrame:
    df = _with_ac(df)
    chans = _channels(df)
    # Unix: the local clock read as UTC, as in REFIT where Time == Unix (scripts/refit.py shifts it)
    unix = (df["timestamp"] - pd.Timestamp(0)) // pd.Timedelta(seconds=1)
    out = pd.DataFrame({"Time": df["timestamp"], "Unix": unix, "Aggregate": df["P_agg"]})
    for i, c in enumerate(chans, 1):
        out[f"Appliance{i}"] = df[c]
    out["Issues"] = df["issues"]
    return out


def main(house: int) -> None:
    folder = PLEGMA / f"House_{house:02d}" / "Electric_data"
    df = pd.concat(
        pd.read_csv(f, parse_dates=["timestamp"]) for f in sorted(folder.glob("20*.csv"))
    )
    out = to_refit(df)
    path = ROOT / "dataset" / f"CLEAN_House{100 + house}.csv"
    out.to_csv(path, index=False)
    print(path, len(out), LABELS(df))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--house", type=int, required=True)
    main(ap.parse_args().house)
