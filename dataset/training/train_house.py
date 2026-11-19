"""Train one REFIT house's own NILM bundle, the way train.ipynb trained House 2.

Same preprocessing (dataset/scripts/eda.ipynb: drop `Issues` rows, under 5 W -> 0, over 10 kW ->
10 kW, 15 s mean on the CSV's local `Time`), same model, losses and time split (train | 1 day gap |
val | test = last 20 %), and the configuration train.ipynb chose for House 2 (focal, 256 steps),
so stage A only picks the epoch count: 5 seeds with early stopping on val. Stage B retrains the 5
seeds on everything before test for the median best epoch; test is scored once. The bundle has the
`wattprint-nilm/2` format the worker loads.

    uv run python dataset/training/train_house.py --house 5
    -> dataset/models/nilm/house5/nilm_pipeline.pt (+ .json summary)
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import torch.nn.functional as F  # noqa: N812
from torch.utils.data import DataLoader, TensorDataset

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.ml.nilm.GRUDetector import GRUConfig, GRUDetector  # noqa: E402
from app.ml.nilm.NILMFormerRegressor import NILMFormerConfig, NILMFormerRegressor  # noqa: E402

# Label -> CSV channel per house (CLEAN_READ_ME_081116.txt; NILMTK's REFIT metadata agrees, its
# meter k+1 is Appliance<k>), label order as the House 2 bundle. House 6 has a freezer, no fridge.
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
ON_THRESHOLD_W = {"Fridge": 50, "Freezer": 50, "WashMach": 20, "Dishwash": 10,
                  "Microwave": 200, "Toaster": 200, "Kettle": 1000}

SAMPLE = pd.Timedelta(seconds=15)
WINDOW, BASE_L = 256, 128
MIN_W, MAX_W = 5, 10_000
SEEDS = [11, 22, 33, 44, 55]
LAMBDA, FOCAL_GAMMA = 5.0, 2.0
EPOCHS, PATIENCE = 50, 7
BATCH = max(64 // (WINDOW // BASE_L), 8)
REG_LR, DET_LR = 1e-4, 1e-3
POS_WEIGHT_MAX = 30.0
TAU_W = 10_000.0
TEST_FRACTION, VAL_FRACTION, VAL_GAP = 0.2, 0.15, pd.Timedelta(days=1)
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")


def time_features(index: pd.DatetimeIndex) -> np.ndarray:
    values = []
    for value, period in (
        (index.minute, 60),
        (index.hour, 24),
        (index.day_of_week, 7),
        (index.month - 1, 12),
    ):
        angle = 2 * np.pi * np.asarray(value, dtype=np.float64) / period
        values.extend((np.sin(angle), np.cos(angle)))
    return np.asarray(values, dtype=np.float32)


def load(house: int):
    channels = list(CHANNELS[house].values())
    cols = ["Aggregate", *channels]
    df = pd.read_csv(
        ROOT / "dataset" / f"CLEAN_House{house}.csv", usecols=["Time", *cols, "Issues"]
    )
    df = df.loc[df["Issues"] != 1]
    v = df[cols]
    df[cols] = v.clip(upper=MAX_W).mask(v.notna() & (v < MIN_W), 0)
    frame = df.assign(Time=pd.to_datetime(df["Time"])).set_index("Time")[cols].sort_index()
    frame = frame.resample(SAMPLE).mean()
    valid = np.isfinite(frame.to_numpy()).all(axis=1)
    edges = np.diff(np.r_[0, valid.astype(np.int8), 0])
    starts = [
        s + k * WINDOW
        for s, e in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1), strict=True)
        for k in range((e - s) // WINDOW)
    ]
    ids = np.asarray(starts, dtype=np.int64)[:, None] + np.arange(WINDOW)
    agg = frame["Aggregate"].to_numpy(np.float32)
    y = frame[channels].to_numpy(np.float32).T
    feats = time_features(frame.index)
    x = np.concatenate([agg[ids][:, None], feats[:, ids].transpose(1, 0, 2)], axis=1).astype(
        np.float32
    )
    y = np.ascontiguousarray(y[:, ids].transpose(1, 0, 2))
    return x, y, frame.index[ids[:, 0]], frame.index[ids[:, -1]]


def split(start: pd.DatetimeIndex, end: pd.DatetimeIndex) -> np.ndarray:
    t0, t1 = start.min(), start.max()
    test_start = t0 + (t1 - t0) * (1 - TEST_FRACTION)
    pre = start[end < test_start]
    val_start = pre.min() + (pre.max() - pre.min()) * (1 - VAL_FRACTION)
    out = np.full(len(start), "gap", dtype=object)
    out[end < val_start - VAL_GAP] = "train"
    out[(start >= val_start) & (end < test_start)] = "val"
    out[start >= test_start] = "test"
    out[(start < test_start) & (end >= test_start)] = "cross"  # would leak test steps: never used
    return out


def detector_inputs(xb):
    agg_kw = xb[:, :1] / 1000.0
    return torch.cat(
        [agg_kw, torch.diff(agg_kw, dim=-1, prepend=agg_kw[..., :1]), xb[:, 1:]], dim=1
    )


def regressor_inputs(xb):
    return torch.cat([xb[:, :1] / TAU_W, xb[:, 1:]], dim=1)


def classification_loss(logits, ob, pos_weight):
    bce = F.binary_cross_entropy_with_logits(logits, ob, reduction="none")
    p = torch.sigmoid(logits)
    p_t = p * ob + (1 - p) * (1 - ob)
    return ((1 + (pos_weight - 1) * ob) * (1 - p_t).pow(FOCAL_GAMMA) * bce).mean()


def losses(reg, det, batch, scale_w, pos_weight):
    xb, yb_w, ob = (b.to(DEVICE) for b in batch)
    yb = yb_w / scale_w
    y_hat, logits = reg(regressor_inputs(xb)), det(detector_inputs(xb))
    loss_reg = (ob * (y_hat - yb) ** 2).sum() / ob.sum().clamp(min=1)
    gated = torch.sigmoid(logits) * y_hat.detach().clamp(min=0)
    loss_crit = F.mse_loss(gated, yb) + F.mse_loss(gated.mean(-1), yb.mean(-1))
    return loss_reg, classification_loss(logits, ob, pos_weight), loss_crit


def train_seed(x, y, on, seed, fit, val, epochs, cfg_det, cfg_reg):
    torch.manual_seed(seed)
    np.random.seed(seed)
    scale = np.maximum(y[fit].std(axis=(0, 2)), 1e-6).astype(np.float32)
    scale_w = torch.as_tensor(scale, device=DEVICE)[None, :, None]
    p = on[fit].mean(axis=(0, 2))
    pos_weight = torch.as_tensor(
        np.clip(np.sqrt((1 - p) / np.maximum(p, 1e-6)), 1, POS_WEIGHT_MAX),
        dtype=torch.float32,
        device=DEVICE,
    )[:, None]
    reg, det = NILMFormerRegressor(cfg_reg).to(DEVICE), GRUDetector(cfg_det).to(DEVICE)
    opts = [
        torch.optim.AdamW(reg.parameters(), lr=REG_LR),
        torch.optim.AdamW(det.parameters(), lr=DET_LR),
    ]

    def loader(ids, shuffle):
        ds = TensorDataset(
            torch.from_numpy(x[ids]),
            torch.from_numpy(y[ids]),
            torch.from_numpy(on[ids].astype(np.float32)),
        )
        gen = torch.Generator().manual_seed(seed) if shuffle else None
        return DataLoader(ds, batch_size=BATCH, shuffle=shuffle, generator=gen)

    fit_l, val_l = loader(fit, True), (loader(val, False) if val is not None else None)
    best = {"score": float("inf"), "epoch": 0}
    for epoch in range(1, epochs + 1):
        reg.train(), det.train()
        for batch in fit_l:
            r, c, k = losses(reg, det, batch, scale_w, pos_weight)
            for o in opts:
                o.zero_grad(set_to_none=True)
            (r + c + LAMBDA * k).backward()
            for o in opts:
                o.step()
        if val_l is None:
            continue
        reg.eval(), det.eval()
        with torch.no_grad():
            score = float(
                np.mean([float(sum(losses(reg, det, b, scale_w, pos_weight))) for b in val_l])
            )
        if score < best["score"]:
            best = {
                "score": score,
                "epoch": epoch,
                "regressor": copy.deepcopy(reg.state_dict()),
                "detector": copy.deepcopy(det.state_dict()),
            }
        print(f"  seed {seed} epoch {epoch:2d} val {score:.4f} (best {best['epoch']})", flush=True)
        if epoch - best["epoch"] >= PATIENCE:
            break
    if val_l is None:
        best = {"epoch": epochs, "regressor": reg.state_dict(), "detector": det.state_dict()}
    return {
        "seed": seed,
        "best_epoch": best["epoch"],
        "scale_w": scale.tolist(),
        "detector_config": asdict(cfg_det),
        "regressor_config": asdict(cfg_reg),
        "detector_state": {k: v.cpu() for k, v in best["detector"].items()},
        "regressor_state": {k: v.cpu() for k, v in best["regressor"].items()},
    }


@torch.no_grad()
def predict(members, x):
    dets, regs, scales = [], [], []
    for m in members:
        d = GRUDetector(GRUConfig(**m["detector_config"]))
        d.load_state_dict(m["detector_state"])
        r = NILMFormerRegressor(NILMFormerConfig(**m["regressor_config"]))
        r.load_state_dict(m["regressor_state"])
        dets.append(d.to(DEVICE).eval()), regs.append(r.to(DEVICE).eval())
        scales.append(torch.as_tensor(m["scale_w"], device=DEVICE))
    p_out, a_out = [], []
    for i in range(0, len(x), 64):
        xb = torch.from_numpy(x[i : i + 64]).to(DEVICE)
        p_on = torch.stack([torch.sigmoid(d(detector_inputs(xb))) for d in dets]).mean(0)
        power = torch.stack(
            [r(regressor_inputs(xb)) * s[None, :, None] for r, s in zip(regs, scales, strict=True)]
        )
        a_out.append((p_on * power.median(0).values.clamp(min=0)).cpu().numpy())
        p_out.append(p_on.cpu().numpy())
    return np.concatenate(p_out), np.concatenate(a_out)


def onoff_f1(t, p):
    tp, fp, fn = (t & p).sum(), (~t & p).sum(), (t & ~p).sum()
    return 2 * tp / max(2 * tp + fp + fn, 1)


def evaluate(pred, p_on, true, true_on, thresholds, labels):
    """Per device and macro, the metrics of train.ipynb §6 (energy matched step by step)."""
    k = SAMPLE.total_seconds() / 3.6e6
    rows = {}
    for c, name in enumerate(labels):
        t, p = true[:, c], pred[:, c]
        match = np.minimum(t, p).sum()
        on_c = true_on[:, c]
        rows[name] = {
            "true kWh": t.sum() * k,
            "pred kWh": p.sum() * k,
            "kWh err %": 100 * (p.sum() / max(t.sum(), 1e-9) - 1),
            "energy F1": 2 * match / max(p.sum() + t.sum(), 1e-9),
            "F1 ON/OFF": onoff_f1(on_c, p_on[:, c] >= thresholds[c]),
        }
    table = pd.DataFrame(rows).T
    summary = {
        "energy F1": table["energy F1"].mean(),
        "F1 ON/OFF": table["F1 ON/OFF"].mean(),
        "mean |kWh err| %": table["kWh err %"].abs().mean(),
        "total kWh err %": 100 * (table["pred kWh"].sum() / table["true kWh"].sum() - 1),
    }
    return table, summary


def main(house: int) -> None:
    t_start = time.time()
    labels = list(CHANNELS[house])
    on_w = np.array([ON_THRESHOLD_W[label] for label in labels], dtype=np.float32)
    x, y, start, end = load(house)
    on = y >= on_w[None, :, None]
    lab = split(start, end)
    ids = {s: np.flatnonzero(lab == s) for s in ("train", "val", "test")}
    pretest = np.flatnonzero((lab != "test") & (lab != "cross"))
    print(
        f"house {house} on {DEVICE}: {len(x):,} windows of {WINDOW} | "
        + " ".join(f"{s} {len(v):,}" for s, v in ids.items()),
        flush=True,
    )
    cfg_det = GRUConfig(c_in=x.shape[1] + 1, c_out=len(labels))
    cfg_reg = NILMFormerConfig(c_out=len(labels))

    print("stage A: epochs by early stopping on val", flush=True)
    stage_a = [
        train_seed(x, y, on, s, ids["train"], ids["val"], EPOCHS, cfg_det, cfg_reg) for s in SEEDS
    ]
    final_epochs = int(np.median([m["best_epoch"] for m in stage_a]))
    p_val, _ = predict(stage_a, x[ids["val"]])
    grid = np.linspace(0.02, 0.98, 49)
    thresholds = np.array(
        [
            grid[int(np.argmax([onoff_f1(on[ids["val"]][:, c], p_val[:, c] >= t) for t in grid]))]
            for c in range(len(labels))
        ],
        dtype=np.float32,
    )

    print(
        f"stage B: {len(SEEDS)} seeds x {final_epochs} epochs on {len(pretest):,} windows",
        flush=True,
    )
    final = [train_seed(x, y, on, s, pretest, None, final_epochs, cfg_det, cfg_reg) for s in SEEDS]

    p_test, a_test = predict(final, x[ids["test"]])
    table, summary = evaluate(a_test, p_test, y[ids["test"]], on[ids["test"]], thresholds, labels)
    print(
        table.round(3).to_string(),
        "\n",
        {k: round(float(v), 3) for k, v in summary.items()},
        flush=True,
    )

    out_dir = ROOT / "dataset" / "models" / "nilm" / f"house{house}"
    out_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "house": house,
        "config": "focal_L256",
        "det_loss": "focal",
        "focal_gamma": FOCAL_GAMMA,
        "lambda": LAMBDA,
        "final_epochs": final_epochs,
        "seeds": SEEDS,
        "stage_a_best_epochs": [m["best_epoch"] for m in stage_a],
        "trained_until": str(end[lab != "test"].max()),
        "test_from": str(start[ids["test"]].min()),
        "test_summary": {k: float(v) for k, v in summary.items()},
        "test_by_device": json.loads(table.to_json(orient="index")),
        "minutes": round((time.time() - t_start) / 60, 1),
    }
    bundle = {
        "format": "wattprint-nilm/2",
        "appliances": list(CHANNELS[house].values()),
        "labels": labels,
        "on_threshold_w": on_w.tolist(),
        "gate": "soft",
        "event_thresholds": thresholds.tolist(),
        "tau_w": TAU_W,
        "sample_seconds": int(SAMPLE.total_seconds()),
        "window": WINDOW,
        "input": f"(B, 9, {WINDOW}) float32: aggregate W (15 s mean, under 5 W -> 0, "
        "over 10 kW -> 10 kW) + 8 sin/cos time features on the home's wall clock",
        "output": "appliance W (B, C, L) = P(ON) x power",
        "members": [
            {
                k: m[k]
                for k in (
                    "seed",
                    "scale_w",
                    "detector_config",
                    "regressor_config",
                    "detector_state",
                    "regressor_state",
                )
            }
            for m in final
        ],
        "meta": meta,
    }
    torch.save(bundle, out_dir / "nilm_pipeline.pt")
    (out_dir / "nilm_pipeline.json").write_text(
        json.dumps(
            {k: v for k, v in bundle.items() if k != "members"}, indent=2, ensure_ascii=False
        )
    )
    loaded = torch.load(out_dir / "nilm_pipeline.pt", map_location="cpu", weights_only=True)
    assert loaded["labels"] == labels and len(loaded["members"]) == len(SEEDS)
    print(f"saved {out_dir / 'nilm_pipeline.pt'} in {meta['minutes']} min", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--house", type=int, required=True, choices=sorted(CHANNELS))
    main(ap.parse_args().house)
