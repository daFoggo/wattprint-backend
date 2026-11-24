"""Research v3, step 2: the ON/OFF detector alone, retrained in variants on one house's own split.

Same data, preprocessing and time split as dataset/training/train_house.py (train | 1 day gap |
val | test = last 20 %). Each variant trains the GRU detector on its focal loss only (no regressor,
so the comparison is the detector's own), early stops on val, picks each device's cut on val by
F1, and is scored once on test against the raw ON labels (aggregate-free: plug W >= the device's
ON threshold). Seeds 11, 22, 33.

Variants:
  base      the production inputs (aggregate kW, its step change, 8 time features), window 256
  baseload  + the window's rolling minimum of the aggregate (15 min, centred) and the aggregate
            above it: a fridge's 80 W compressor is a step on the base load, not on the total
  clean     base inputs, training labels cleaned: ON runs and OFF gaps shorter than a device's
            minimum (fridge 2 min, others 30 s) taken out; scored on the raw labels all the same
  long      base inputs, window 512 (2 h 8 min: several fridge cycles in view)
  joint     the production recipe: detector and regressor trained together, the gated loss
            (P(ON) x the regressor's power against the plug, weight 5) flowing into the detector;
            the control for "does the regressor's loss hurt the ON/OFF detector?"

    uv run python dataset/research_v3/onoff_train.py --house 5 --variants base baseload clean long
    -> dataset/research_v3/onoff_train_house5.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import torch.nn.functional as F  # noqa: N812
from torch.utils.data import DataLoader, TensorDataset

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "dataset" / "training"))
sys.path.insert(0, str(ROOT / "dataset" / "research_v3"))
sys.path.insert(0, str(ROOT))

import train_house as th  # noqa: E402
from onoff_post import min_durations  # noqa: E402

from app.ml.nilm.GRUDetector import GRUConfig, GRUDetector  # noqa: E402

SEEDS = [11, 22, 33]
EPOCHS, PATIENCE = 40, 6
BASELOAD_STEPS = 61  # 15 min of 15 s, centred
MIN_RUN = {"Fridge": 8, "Freezer": 8}  # steps; others 2 (30 s)


def baseload_inputs(xb: torch.Tensor) -> torch.Tensor:
    base = th.detector_inputs(xb)
    agg = base[:, :1]
    floor = -F.max_pool1d(-agg, BASELOAD_STEPS, stride=1, padding=BASELOAD_STEPS // 2)
    return torch.cat([base, floor, agg - floor], dim=1)


FLOORS = {
    "2h": 481,
    "6h": 1441,
}  # steps of 15 s, centred: a raised base shows in these, a compressor does not


def load_context(house: int):
    """train_house.load plus the aggregate's rolling floor over 2 h and 6 h (kW), taken over the whole
    series: a 64-min window cannot tell a raised base load from a running compressor."""
    channels = list(th.CHANNELS[house].values())
    cols = ["Aggregate", *channels]
    df = pd.read_csv(
        ROOT / "dataset" / f"CLEAN_House{house}.csv", usecols=["Time", *cols, "Issues"]
    )
    df = df.loc[df["Issues"] != 1]
    v = df[cols]
    df[cols] = v.clip(upper=th.MAX_W).mask(v.notna() & (v < th.MIN_W), 0)
    frame = df.assign(Time=pd.to_datetime(df["Time"])).set_index("Time")[cols].sort_index()
    frame = frame.resample(th.SAMPLE).mean()
    floors = [
        frame["Aggregate"].rolling(n, center=True, min_periods=1).min().to_numpy(np.float32) / 1000
        for n in FLOORS.values()
    ]
    x, y, start, end = th.load(house)
    pos = frame.index.get_indexer(start)
    ids = pos[:, None] + np.arange(th.WINDOW)
    extra = np.stack([f[ids] for f in floors], axis=1)
    return np.concatenate([x, extra], axis=1).astype(np.float32), y, start, end


def context_inputs(xb: torch.Tensor) -> torch.Tensor:
    base = baseload_inputs(xb)  # ..., floor 2h, floor 6h, floor 15 min, agg - floor 15 min
    return torch.cat([base, base[:, :1] - xb[:, -len(FLOORS) : -len(FLOORS) + 1]], dim=1)


def clean_labels(on: np.ndarray, labels: list[str]) -> np.ndarray:
    out = on.copy()
    breaks = np.zeros(on.shape[-1], dtype=bool)
    breaks[0] = True
    for c, label in enumerate(labels):
        n = MIN_RUN.get(label, 2)
        for w in range(len(on)):
            out[w, c] = min_durations(on[w, c], n, n, breaks)
    return out


def f1_parts(t: np.ndarray, p: np.ndarray) -> dict:
    tp, fp, fn = (t & p).sum(), (~t & p).sum(), (t & ~p).sum()
    return {
        "F1": float(2 * tp / max(2 * tp + fp + fn, 1)),
        "P": float(tp / max(tp + fp, 1)),
        "R": float(tp / max(tp + fn, 1)),
    }


def train_detector(x, on_train, on_val, ids, seed, inputs, c_in, n_out):
    torch.manual_seed(seed)
    np.random.seed(seed)
    p = on_train[ids["train"]].mean(axis=(0, 2))
    pos_weight = torch.as_tensor(
        np.clip(np.sqrt((1 - p) / np.maximum(p, 1e-6)), 1, th.POS_WEIGHT_MAX),
        dtype=torch.float32,
        device=th.DEVICE,
    )[:, None]
    det = GRUDetector(GRUConfig(c_in=c_in, c_out=n_out)).to(th.DEVICE)
    opt = torch.optim.AdamW(det.parameters(), lr=th.DET_LR)

    def loader(idx, labels, shuffle):
        ds = TensorDataset(
            torch.from_numpy(x[idx]), torch.from_numpy(labels[idx].astype(np.float32))
        )
        gen = torch.Generator().manual_seed(seed) if shuffle else None
        return DataLoader(ds, batch_size=th.BATCH, shuffle=shuffle, generator=gen)

    fit_l, val_l = loader(ids["train"], on_train, True), loader(ids["val"], on_val, False)
    best = {"loss": float("inf"), "epoch": 0, "state": None}
    for epoch in range(1, EPOCHS + 1):
        det.train()
        for xb, ob in fit_l:
            xb, ob = xb.to(th.DEVICE), ob.to(th.DEVICE)
            loss = th.classification_loss(det(inputs(xb)), ob, pos_weight)
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
        if epoch - best["epoch"] >= PATIENCE:
            break
    det.load_state_dict(best["state"])
    return det.eval(), best["epoch"]


@torch.no_grad()
def p_on(det, x, inputs):
    out = []
    for i in range(0, len(x), 256):
        out.append(torch.sigmoid(det(inputs(torch.from_numpy(x[i : i + 256]).to(th.DEVICE)))).cpu())
    return torch.cat(out).numpy()


def run_variant(house: int, variant: str) -> dict:
    th.WINDOW = 512 if variant == "long" else 256
    th.BATCH = max(64 // (th.WINDOW // th.BASE_L), 8)
    labels = list(th.CHANNELS[house])
    on_w = np.array([th.ON_THRESHOLD_W[k] for k in labels], dtype=np.float32)
    x, y, start, end = load_context(house) if variant == "context" else th.load(house)
    on = y >= on_w[None, :, None]
    lab = th.split(start, end)
    ids = {s: np.flatnonzero(lab == s) for s in ("train", "val", "test")}
    on_train = clean_labels(on, labels) if variant == "clean" else on
    inputs = {"baseload": baseload_inputs, "context": context_inputs}.get(
        variant, th.detector_inputs
    )
    c_in = x.shape[1] + {"baseload": 3, "context": 4}.get(variant, 1)
    grid = np.linspace(0.02, 0.98, 49)
    seeds = []
    for seed in SEEDS:
        t0 = time.time()
        if variant == "joint":
            m = th.train_seed(
                x,
                y,
                on,
                seed,
                ids["train"],
                ids["val"],
                EPOCHS,
                GRUConfig(c_in=c_in, c_out=len(labels)),
                th.NILMFormerConfig(c_out=len(labels)),
            )
            det = GRUDetector(GRUConfig(**m["detector_config"])).to(th.DEVICE)
            det.load_state_dict(m["detector_state"])
            det, epoch = det.eval(), m["best_epoch"]
        else:
            det, epoch = train_detector(x, on_train, on_train, ids, seed, inputs, c_in, len(labels))
        pv, pt = p_on(det, x[ids["val"]], inputs), p_on(det, x[ids["test"]], inputs)
        per = {}
        for c, label in enumerate(labels):
            tv, tt = on[ids["val"]][:, c], on[ids["test"]][:, c]
            cut = grid[int(np.argmax([f1_parts(tv, pv[:, c] >= g)["F1"] for g in grid]))]
            per[label] = {**f1_parts(tt, pt[:, c] >= cut), "cut": float(cut)}
        seeds.append(
            {
                "seed": seed,
                "epoch": epoch,
                "devices": per,
                "minutes": round((time.time() - t0) / 60, 2),
            }
        )
        print(
            f"house {house} {variant} seed {seed} epoch {epoch}: "
            + " ".join(f"{k} {v['F1']:.3f}" for k, v in per.items()),
            flush=True,
        )
    mean = {
        label: {
            m: float(np.mean([s["devices"][label][m] for s in seeds])) for m in ("F1", "P", "R")
        }
        for label in labels
    }
    spread = {label: float(np.std([s["devices"][label]["F1"] for s in seeds])) for label in labels}
    return {
        "seeds": seeds,
        "mean": mean,
        "F1 sd": spread,
        "macro F1": float(np.mean([v["F1"] for v in mean.values()])),
    }


def main(house: int, variants: list[str]) -> None:
    path = ROOT / "dataset" / "research_v3" / f"onoff_train_house{house}.json"
    out = json.loads(path.read_text()) if path.exists() else {"house": house, "variants": {}}
    for v in variants:
        out["variants"][v] = run_variant(house, v)
        path.write_text(json.dumps(out, indent=2))
        m = out["variants"][v]
        print(
            f"== house {house} {v}: macro F1 {m['macro F1']:.3f} | "
            + " ".join(
                f"{k} {d['F1']:.3f} (P {d['P']:.2f} R {d['R']:.2f})" for k, d in m["mean"].items()
            ),
            flush=True,
        )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--house", type=int, required=True, choices=sorted(th.CHANNELS))
    ap.add_argument("--variants", nargs="+", default=["base", "baseload", "clean", "long"])
    a = ap.parse_args()
    main(a.house, a.variants)
