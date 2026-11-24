"""Research v3: where a device's extra kWh comes from in the split pipeline (one seed).

Predicted kWh = power on steps both call ON (true ON) + power on steps only the detector calls ON
(false ON). Against the plug: kWh on true ON steps, kWh the detector missed (false OFF). So an
overcount is told apart: the detector's false ONs, or the regressor's power level when it is ON.

    uv run python dataset/research_v3/overcount.py --house 2 --seed 11
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from scipy.ndimage import maximum_filter1d

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "dataset" / "training"))
sys.path.insert(0, str(ROOT / "dataset" / "research_v3"))
sys.path.insert(0, str(ROOT))

import train_house as th  # noqa: E402
from onoff_train import EPOCHS, baseload_inputs, p_on, train_detector  # noqa: E402
from pipeline_eval import cuts, power  # noqa: E402

from app.ml.nilm.GRUDetector import GRUConfig  # noqa: E402
from app.ml.nilm.NILMFormerRegressor import NILMFormerConfig  # noqa: E402

K = th.SAMPLE.total_seconds() / 3.6e6
NEAR = 8  # 2 min of 15 s steps


def main(house: int, seed: int) -> None:
    labels = list(th.CHANNELS[house])
    on_w = np.array([th.ON_THRESHOLD_W[k] for k in labels], dtype=np.float32)
    x, y, start, end = th.load(house)
    on = y >= on_w[None, :, None]
    lab = th.split(start, end)
    ids = {s: np.flatnonzero(lab == s) for s in ("train", "val", "test")}
    lam, th.LAMBDA = th.LAMBDA, 0.0
    reg = th.train_seed(
        x,
        y,
        on,
        seed,
        ids["train"],
        ids["val"],
        EPOCHS,
        GRUConfig(c_in=x.shape[1] + 1, c_out=len(labels)),
        NILMFormerConfig(c_out=len(labels)),
    )
    th.LAMBDA = lam
    det, _ = train_detector(x, on, on, ids, seed, baseload_inputs, x.shape[1] + 3, len(labels))
    c = cuts(p_on(det, x[ids["val"]], baseload_inputs), on[ids["val"]])
    pt = p_on(det, x[ids["test"]], baseload_inputs)
    w, yt, ot = power(reg, x[ids["test"]]), y[ids["test"]], on[ids["test"]]
    out = {}
    for i, k in enumerate(labels):
        called = pt[:, i] >= c[i]
        t_on, wi, yi = ot[:, i], w[:, i], yt[:, i]
        tp, fp, fn = called & t_on, called & ~t_on, ~called & t_on
        # false ONs within NEAR steps of a true ON step: a smeared edge, not an invented run
        near = maximum_filter1d(t_on.astype(np.uint8), 2 * NEAR + 1, axis=1).astype(bool)
        out[k] = {
            "true kWh": float(yi.sum() * K),
            "pred kWh": float((called * wi).sum() * K),
            "pred on true ON": float((tp * wi).sum() * K),
            "plug on true ON": float((tp * yi).sum() * K),
            "pred on false ON": float((fp * wi).sum() * K),
            "plug on false ON": float((fp * yi).sum() * K),
            "plug missed (false OFF)": float((fn * yi).sum() * K),
            "mean W pred / plug on true ON": [
                float(wi[tp].mean()) if tp.any() else None,
                float(yi[tp].mean()) if tp.any() else None,
            ],
            "false ON share of called": float(fp.sum() / max(called.sum(), 1)),
            "false ON kWh at an edge (<= 2 min)": float(((fp & near) * wi).sum() * K),
        }
        row = {a: (round(b, 1) if isinstance(b, float) else b) for a, b in out[k].items()}
        print(k, row, flush=True)
    np.savez_compressed(  # for analyses that need no retraining
        ROOT / "dataset" / "research_v3" / f"overcount_house{house}_seed{seed}.npz",
        p_on=pt.astype(np.float16),
        cuts=c,
        power=w.astype(np.float16),
        y=yt.astype(np.float16),
        x=x[ids["test"]].astype(np.float32),
        labels=np.array(labels),
    )
    (ROOT / "dataset" / "research_v3" / f"overcount_house{house}_seed{seed}.json").write_text(
        json.dumps(out, indent=2)
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--house", type=int, required=True)
    ap.add_argument("--seed", type=int, default=11)
    a = ap.parse_args()
    main(a.house, a.seed)
