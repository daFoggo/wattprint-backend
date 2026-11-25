"""Plegma survey: per house, each appliance's coverage (non-NaN share), kWh and days of data.

uv run python dataset/research_v4/plegma_survey.py   ->  dataset/research_v4/plegma_survey.json
"""

import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
PLEGMA = ROOT / "dataset" / "external" / "plegma" / "Clean_Dataset"
STEP_H = 10 / 3600  # samples are 10 s


def main() -> None:
    out = {}
    for house in sorted(PLEGMA.glob("House_*")):
        df = pd.concat(
            pd.read_csv(f, index_col=0, parse_dates=True)
            for f in sorted((house / "Electric_data").glob("20*.csv"))
        )
        meta = pd.read_csv(house / "Electric_data" / "appliances_metadata.csv").set_index(
            "appliance"
        )
        row = {
            "days": round((df.index.max() - df.index.min()).days),
            "issues": float(df["issues"].mean()),
        }
        row["aggregate_kwh"] = float(df["P_agg"].sum() * STEP_H / 1000)
        for c in df.columns.difference(["V", "A", "P_agg", "issues"]):
            row[c] = {
                "coverage": round(float(df[c].notna().mean()), 3),
                "kwh": round(float(df[c].sum() * STEP_H / 1000), 1),
                "wattage": float(meta.loc[c, "wattage [W]"]) if c in meta.index else None,
            }
        out[house.name] = row
        print(
            house.name,
            {
                k: (v if not isinstance(v, dict) else (v["coverage"], v["kwh"]))
                for k, v in row.items()
            },
            flush=True,
        )
    (ROOT / "dataset" / "research_v4" / "plegma_survey.json").write_text(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
