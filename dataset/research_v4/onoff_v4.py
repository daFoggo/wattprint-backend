"""Research v4: the ON/OFF detector with hard negatives, a stacked first pass and a heater exclusion.

Baseline is research_v3's `context` variant (same data, split, seeds, inputs): its stored results are
`dataset/research_v3/onoff_train_house{N}.json`. A variant adds to those inputs:

  hardneg  windows where a cross-fitted first pass invented runs are up-weighted in the focal loss
  stack    the first pass's P(ON) of all devices over the window as extra inputs (the fridge's rhythm
           is in it: the net sees when runs started and stopped); first pass cross-fitted in time
  excl     a penalty when the short heaters (microwave, toaster, kettle) are called ON together
  all      the three together

    uv run python dataset/research_v4/onoff_v4.py --house 5 --variants hardneg stack excl all
    -> dataset/research_v4/onoff_v4_house5.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F  # noqa: N812
from torch.utils.data import DataLoader, TensorDataset

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "dataset" / "training"))
sys.path.insert(0, str(ROOT / "dataset" / "research_v3"))
sys.path.insert(0, str(ROOT))

import onoff_train as ot  # noqa: E402
import train_house as th  # noqa: E402

from app.ml.nilm.GRUDetector import GRUConfig, GRUDetector  # noqa: E402

SEEDS = ot.SEEDS
HEATERS = ("Microwave", "Toaster", "Kettle")
FP_GAIN, W_MAX, EXCL_GAIN = (
    20.0,
    8.0,
    1.0,
)  # shortcut: untuned constants, tune per house if v4 shows a gain


def element_loss(logits, ob, pos_weight):
    """th.classification_loss without the mean: (B, C, L)."""
    bce = F.binary_cross_entropy_with_logits(logits, ob, reduction="none")
    p = torch.sigmoid(logits)
    p_t = p * ob + (1 - p) * (1 - ob)
    return (1 + (pos_weight - 1) * ob) * (1 - p_t).pow(th.FOCAL_GAMMA) * bce


def fit(x, on, train_ids, val_ids, seed, inputs, c_in, n_out, weights=None, heaters=None):
    """ot.train_detector with per-window-device weights and the heater exclusion; early stop on val."""
    torch.manual_seed(seed)
    np.random.seed(seed)
    p = on[train_ids].mean(axis=(0, 2))
    pos_weight = torch.as_tensor(
        np.clip(np.sqrt((1 - p) / np.maximum(p, 1e-6)), 1, th.POS_WEIGHT_MAX),
        dtype=torch.float32,
        device=th.DEVICE,
    )[:, None]
    det = GRUDetector(GRUConfig(c_in=c_in, c_out=n_out)).to(th.DEVICE)
    opt = torch.optim.AdamW(det.parameters(), lr=th.DET_LR)
    w = np.ones((len(train_ids), n_out), np.float32) if weights is None else weights
    fit_l = DataLoader(
        TensorDataset(
            torch.from_numpy(x[train_ids]),
            torch.from_numpy(on[train_ids].astype(np.float32)),
            torch.from_numpy(w),
        ),
        batch_size=th.BATCH,
        shuffle=True,
        generator=torch.Generator().manual_seed(seed),
    )
    val_l = DataLoader(
        TensorDataset(
            torch.from_numpy(x[val_ids]), torch.from_numpy(on[val_ids].astype(np.float32))
        ),
        batch_size=th.BATCH,
    )
    best = {"loss": float("inf"), "epoch": 0, "state": None}
    for epoch in range(1, ot.EPOCHS + 1):
        det.train()
        for xb, ob, wb in fit_l:
            xb, ob, wb = xb.to(th.DEVICE), ob.to(th.DEVICE), wb.to(th.DEVICE)
            logits = det(inputs(xb))
            loss = (element_loss(logits, ob, pos_weight) * wb[:, :, None]).mean()
            if heaters:
                loss = (
                    loss + EXCL_GAIN * F.relu(torch.sigmoid(logits)[:, heaters].sum(1) - 1).mean()
                )
            opt.zero_grad(set_to_none=True)
            loss.backward()
            opt.step()
        det.eval()
        with torch.no_grad():
            val = float(
                np.mean(
                    [
                        float(
                            th.classification_loss(
                                det(inputs(xb.to(th.DEVICE))), ob.to(th.DEVICE), pos_weight
                            )
                        )
                        for xb, ob in val_l
                    ]
                )
            )
        if val < best["loss"]:
            best = {
                "loss": val,
                "epoch": epoch,
                "state": {k: v.clone() for k, v in det.state_dict().items()},
            }
        if epoch - best["epoch"] >= ot.PATIENCE:
            break
    det.load_state_dict(best["state"])
    return det.eval(), best["epoch"]


def first_pass(x, on, ids, seed, n_out):
    """Cross-fitted P(ON) of the context detector: each half of train is predicted by the model trained on
    the other half; val and test get the mean of the two. Returns (p over all windows, a copy of train's fp mass)."""
    tr = ids["train"]
    halves = [tr[: len(tr) // 2], tr[len(tr) // 2 :]]
    p1 = np.zeros((len(x), n_out, x.shape[-1]), np.float32)
    held = np.concatenate([ids["val"], ids["test"]])
    for a, b in ((0, 1), (1, 0)):
        det, _ = fit(x, on, halves[a], ids["val"], seed, ot.context_inputs, x.shape[1] + 4, n_out)
        p1[halves[b]] = ot.p_on(det, x[halves[b]], ot.context_inputs)
        p1[held] += ot.p_on(det, x[held], ot.context_inputs) / 2
    return p1


def run_variant(house: int, variant: str) -> dict:
    th.WINDOW = 256
    th.BATCH = max(64 // (th.WINDOW // th.BASE_L), 8)
    labels = list(th.CHANNELS[house])
    n_out = len(labels)
    on_w = np.array([th.ON_THRESHOLD_W[k] for k in labels], dtype=np.float32)
    x, y, start, end = ot.load_context(house)
    on = y >= on_w[None, :, None]
    lab = th.split(start, end)
    ids = {s: np.flatnonzero(lab == s) for s in ("train", "val", "test")}
    use_w, use_stack, use_excl = (
        variant in ("hardneg", "all"),
        variant in ("stack", "all"),
        variant in ("excl", "all"),
    )
    heaters = [labels.index(k) for k in HEATERS if k in labels] if use_excl else None
    grid = np.linspace(0.02, 0.98, 49)
    seeds = []
    for seed in SEEDS:
        t0 = time.time()
        xs, inputs, c_in, weights = x, ot.context_inputs, x.shape[1] + 4, None
        if use_w or use_stack:
            p1 = first_pass(x, on, ids, seed, n_out)
            if use_w:
                fp = (p1[ids["train"]] * ~on[ids["train"]]).mean(
                    axis=-1
                )  # (N, C): soft false-ON mass
                weights = np.minimum(1 + FP_GAIN * fp, W_MAX).astype(np.float32)
            if use_stack:
                xs = np.concatenate([x, p1], axis=1)
                c_in += n_out

                def inputs(xb, n=n_out):
                    return torch.cat([ot.context_inputs(xb[:, :-n]), xb[:, -n:]], dim=1)

        det, epoch = fit(
            xs, on, ids["train"], ids["val"], seed, inputs, c_in, n_out, weights, heaters
        )
        pv, pt = ot.p_on(det, xs[ids["val"]], inputs), ot.p_on(det, xs[ids["test"]], inputs)
        per = {}
        for c, label in enumerate(labels):
            tv, tt = on[ids["val"]][:, c], on[ids["test"]][:, c]
            cut = grid[int(np.argmax([ot.f1_parts(tv, pv[:, c] >= g)["F1"] for g in grid]))]
            per[label] = {**ot.f1_parts(tt, pt[:, c] >= cut), "cut": float(cut)}
        seeds.append(
            {
                "seed": seed,
                "epoch": epoch,
                "devices": per,
                "minutes": round((time.time() - t0) / 60, 2),
            }
        )
        print(
            f"house {house} {variant} seed {seed}: "
            + " ".join(f"{k} {v['F1']:.3f}" for k, v in per.items()),
            flush=True,
        )
    mean = {
        l: {m: float(np.mean([s["devices"][l][m] for s in seeds])) for m in ("F1", "P", "R")}
        for l in labels
    }
    return {
        "seeds": seeds,
        "mean": mean,
        "F1 sd": {l: float(np.std([s["devices"][l]["F1"] for s in seeds])) for l in labels},
        "macro F1": float(np.mean([v["F1"] for v in mean.values()])),
    }


def main(house: int, variants: list[str]) -> None:
    path = ROOT / "dataset" / "research_v4" / f"onoff_v4_house{house}.json"
    out = json.loads(path.read_text()) if path.exists() else {"house": house, "variants": {}}
    for v in variants:
        out["variants"][v] = run_variant(house, v)
        path.write_text(json.dumps(out, indent=2))
        m = out["variants"][v]
        print(
            f"== house {house} {v}: macro F1 {m['macro F1']:.3f} | "
            + " ".join(f"{k} {d['F1']:.3f}" for k, d in m["mean"].items()),
            flush=True,
        )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--house", type=int, required=True, choices=sorted(th.CHANNELS))
    ap.add_argument("--variants", nargs="+", default=["hardneg", "stack", "excl", "all"])
    a = ap.parse_args()
    main(a.house, a.variants)
