"""Research v3, step 3: does a better ON/OFF detector give better energy per device?

Two pipelines on one house's own split (dataset/training/train_house.py's data and split), seeds
11, 22, 33, each scored on test per seed and averaged:
  joint   the production recipe: detector and regressor together, the gated loss (weight 5)
          flowing into the detector
  split   the detector alone on its focal loss with the base-load inputs (step 2's best), the
          regressor alone on its own loss (power where the plug is ON), nothing between them
Each with three gates: soft (P(ON) x power, as shipped), hard (power where P(ON) >= the device's
cut, chosen on val by ON/OFF F1) and hard-e (the cut chosen on val by energy F1 instead: ON/OFF F1
rewards calling ON a little too often, energy pays for it in kWh).

    uv run python dataset/research_v3/pipeline_eval.py --house 5
    -> dataset/research_v3/pipeline_eval_house5.json
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
from app.ml.nilm.GRUDetector import GRUConfig, GRUDetector  # noqa: E402
from app.ml.nilm.NILMFormerRegressor import NILMFormerConfig, NILMFormerRegressor  # noqa: E402
from onoff_train import EPOCHS, SEEDS, baseload_inputs, f1_parts, p_on, train_detector  # noqa: E402

K = th.SAMPLE.total_seconds() / 3.6e6


@torch.no_grad()
def power(m: dict, x: np.ndarray) -> np.ndarray:
    r = NILMFormerRegressor(NILMFormerConfig(**m["regressor_config"]))
    r.load_state_dict(m["regressor_state"])
    r = r.to(th.DEVICE).eval()
    s = torch.as_tensor(m["scale_w"], device=th.DEVICE)[None, :, None]
    out = []
    for i in range(0, len(x), 256):
        xb = torch.from_numpy(x[i : i + 256]).to(th.DEVICE)
        out.append((r(th.regressor_inputs(xb)) * s).clamp(min=0).cpu())
    return torch.cat(out).numpy()


def cuts(p_val: np.ndarray, on_val: np.ndarray) -> np.ndarray:
    grid = np.linspace(0.02, 0.98, 49)
    return np.array(
        [grid[int(np.argmax([f1_parts(on_val[:, c], p_val[:, c] >= g)["F1"] for g in grid]))]
         for c in range(p_val.shape[1])]
    )


def energy_cuts(p_val: np.ndarray, w_val: np.ndarray, y_val: np.ndarray) -> np.ndarray:
    grid = np.linspace(0.02, 0.98, 49)
    best = []
    for c in range(p_val.shape[1]):
        t = y_val[:, c].ravel()
        scores = []
        for g in grid:
            pr = ((p_val[:, c] >= g) * w_val[:, c]).ravel()
            scores.append(2 * np.minimum(t, pr).sum() / max(t.sum() + pr.sum(), 1e-9))
        best.append(grid[int(np.argmax(scores))])
    return np.array(best)


def energy(true_w: np.ndarray, pred_w: np.ndarray, labels: list[str]) -> dict:
    rows = {}
    for c, label in enumerate(labels):
        t, p = true_w[:, c], pred_w[:, c]
        rows[label] = {
            "energy F1": float(2 * np.minimum(t, p).sum() / max(t.sum() + p.sum(), 1e-9)),
            "kWh err %": float(100 * (p.sum() / max(t.sum(), 1e-9) - 1)),
        }
    return rows


def main(house: int) -> None:
    labels = list(th.CHANNELS[house])
    on_w = np.array([th.ON_THRESHOLD_W[k] for k in labels], dtype=np.float32)
    x, y, start, end = th.load(house)
    on = y >= on_w[None, :, None]
    lab = th.split(start, end)
    ids = {s: np.flatnonzero(lab == s) for s in ("train", "val", "test")}
    cfg_det = GRUConfig(c_in=x.shape[1] + 1, c_out=len(labels))
    cfg_reg = NILMFormerConfig(c_out=len(labels))
    yt = y[ids["test"]]
    runs: dict[str, list] = {}
    for seed in SEEDS:
        lam = th.LAMBDA
        joint = th.train_seed(x, y, on, seed, ids["train"], ids["val"], EPOCHS, cfg_det, cfg_reg)
        th.LAMBDA = 0.0  # the regressor on its own loss; its detector is not used
        alone = th.train_seed(x, y, on, seed, ids["train"], ids["val"], EPOCHS, cfg_det, cfg_reg)
        th.LAMBDA = lam
        det_split, _ = train_detector(
            x, on, on, ids, seed, baseload_inputs, x.shape[1] + 3, len(labels)
        )
        jd = GRUDetector(GRUConfig(**joint["detector_config"])).to(th.DEVICE)
        jd.load_state_dict(joint["detector_state"])
        for name, det, inputs, reg in (
            ("joint", jd.eval(), th.detector_inputs, joint),
            ("split", det_split, baseload_inputs, alone),
        ):
            pv, pt = p_on(det, x[ids["val"]], inputs), p_on(det, x[ids["test"]], inputs)
            w = power(reg, x[ids["test"]])
            c = cuts(pv, on[ids["val"]])
            ce = energy_cuts(pv, power(reg, x[ids["val"]]), y[ids["val"]])
            flat = lambda a: a.transpose(1, 0, 2).reshape(a.shape[1], -1).T  # noqa: E731
            soft, hard = flat(pt * w), flat((pt >= c[None, :, None]) * w)
            hard_e = flat((pt >= ce[None, :, None]) * w)
            runs.setdefault(name, []).append(
                {
                    "seed": seed,
                    "F1 ON/OFF": {
                        k: f1_parts(flat(on[ids["test"]])[:, i], flat(pt)[:, i] >= c[i])["F1"]
                        for i, k in enumerate(labels)
                    },
                    "soft": energy(flat(yt), soft, labels),
                    "hard": energy(flat(yt), hard, labels),
                    "hard-e": energy(flat(yt), hard_e, labels),
                }
            )
            r = runs[name][-1]
            print(
                f"house {house} seed {seed} {name}: "
                + " ".join(
                    f"{k} F1 {r['F1 ON/OFF'][k]:.2f} soft {r['soft'][k]['energy F1']:.2f}/"
                    f"{r['soft'][k]['kWh err %']:+.0f}% hard {r['hard'][k]['energy F1']:.2f}/"
                    f"{r['hard'][k]['kWh err %']:+.0f}%"
                    for k in labels
                ),
                flush=True,
            )
    summary = {}
    for name, rs in runs.items():
        summary[name] = {
            k: {
                "F1 ON/OFF": float(np.mean([r["F1 ON/OFF"][k] for r in rs])),
                **{
                    f"{g} {m}": float(np.mean([r[g][k][m] for r in rs]))
                    for g in ("soft", "hard", "hard-e")
                    for m in ("energy F1", "kWh err %")
                },
            }
            for k in labels
        }
    out = {"house": house, "seeds": SEEDS, "runs": runs, "mean": summary}
    path = ROOT / "dataset" / "research_v3" / f"pipeline_eval_house{house}.json"
    path.write_text(json.dumps(out, indent=2))
    for name, s in summary.items():
        for k, v in s.items():
            print(f"== {house} {name:5s} {k:9s} " + " ".join(f"{m} {x:.3f}" for m, x in v.items()))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--house", type=int, required=True, choices=sorted(th.CHANNELS))
    main(ap.parse_args().house)
