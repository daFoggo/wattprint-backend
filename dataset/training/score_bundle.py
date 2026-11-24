"""Score a shipped per-house NILM bundle on its house's test split (the last 20 %, never trained on) and
write the per-device scores into the bundle's JSON sidecar as `meta.test_by_device`, as train_house.py
does for a bundle it trains. The API reads them there to say how far each device's estimate can be
trusted. Same data, split, gate (soft: P(ON) x power, as the worker runs it) and metrics as training.

    uv run python dataset/training/score_bundle.py --house 2
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "dataset" / "training"))
sys.path.insert(0, str(ROOT / "dataset" / "research_v3"))
sys.path.insert(0, str(ROOT))

import train_house as th  # noqa: E402
from onoff_post import p_and_power  # noqa: E402


def main(house: int) -> None:
    folder = ROOT / "dataset" / "models" / "nilm" / f"house{house}"
    bundle = torch.load(folder / "nilm_pipeline.pt", map_location="cpu", weights_only=True)
    labels = list(bundle["labels"])
    on_w = np.array(bundle["on_threshold_w"], dtype=np.float32)
    x, y, start, end = th.load(house)
    test = np.flatnonzero(th.split(start, end) == "test")
    p, w = p_and_power(bundle["members"], x[test])
    flat = lambda a: a.transpose(1, 0, 2).reshape(a.shape[1], -1).T  # noqa: E731
    true = flat(y[test])
    table, summary = th.evaluate(
        flat(p * w), flat(p), true, true >= on_w, bundle["event_thresholds"], labels
    )
    sidecar = folder / "nilm_pipeline.json"
    doc = json.loads(sidecar.read_text())
    doc["meta"]["test_from"] = str(start[test].min())
    doc["meta"]["test_by_device"] = json.loads(table.to_json(orient="index"))
    doc["meta"]["test_summary"] = {k: float(v) for k, v in summary.items()}
    sidecar.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
    print(table.round(3).to_string())
    print({k: round(float(v), 3) for k, v in summary.items()})


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--house", type=int, required=True)
    main(ap.parse_args().house)
