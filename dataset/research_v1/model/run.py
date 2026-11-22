"""Train and evaluate v1 source-house NILM model bundles.

Run from the repository root with ``uv run --group nilm python
dataset/research_v1/model/run.py``. Only source-house train/validation windows
are used to fit models, choose stopping epochs, and calibrate event thresholds.
Target test windows are loaded after both source bundles have been frozen.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from torch.utils.data import DataLoader, TensorDataset

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from dataset.research_v1.baseline.run import held_out_indices  # noqa: E402
from dataset.training import train_house as tr  # noqa: E402

OUT = Path(__file__).resolve().parent
VERSION = OUT / "v1"
SOURCES = (2, 5)
TARGETS = (2, 3, 5, 6)
SEEDS = (11, 22)
EPOCHS = 12
PATIENCE = 3
WINDOWS_PER_EPOCH = 512
AGGREGATE_GAIN = (0.9, 1.1)
AGGREGATE_NOISE_STD_W = 15.0


def f1(t: np.ndarray, p: np.ndarray) -> float | None:
    tp = int(np.count_nonzero(t & p))
    fp = int(np.count_nonzero(~t & p))
    fn = int(np.count_nonzero(t & ~p))
    return 2 * tp / (2 * tp + fp + fn) if tp + fn else None


def val_thresholds(prob: np.ndarray, truth: np.ndarray, labels: list[str]) -> np.ndarray:
    grid = np.linspace(0.02, 0.98, 49)
    return np.asarray([
        grid[int(np.argmax([f1(truth[:, j], prob[:, j] >= t) or 0.0 for t in grid]))]
        for j in range(len(labels))
    ], dtype=np.float32)


def model_predict(members: list[dict], x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    return tr.predict(members, x)


def train_seed(x: np.ndarray, y: np.ndarray, on: np.ndarray, seed: int,
               fit: np.ndarray, val: np.ndarray | None, epochs: int,
               det_cfg, reg_cfg) -> dict:
    """Train supported wattprint members with source-only aggregate sensor augmentation."""
    torch.manual_seed(seed)
    np.random.seed(seed)
    scale = np.maximum(y[fit].std(axis=(0, 2)), 1e-6).astype(np.float32)
    scale_w = torch.as_tensor(scale, device=tr.DEVICE)[None, :, None]
    p = on[fit].mean(axis=(0, 2))
    pos_weight = torch.as_tensor(
        np.clip(np.sqrt((1 - p) / np.maximum(p, 1e-6)), 1, tr.POS_WEIGHT_MAX),
        dtype=torch.float32, device=tr.DEVICE,
    )[:, None]
    reg, det = tr.NILMFormerRegressor(reg_cfg).to(tr.DEVICE), tr.GRUDetector(det_cfg).to(tr.DEVICE)
    opt_r = torch.optim.AdamW(reg.parameters(), lr=tr.REG_LR)
    opt_d = torch.optim.AdamW(det.parameters(), lr=tr.DET_LR)
    fit_t = TensorDataset(torch.from_numpy(x[fit]), torch.from_numpy(y[fit]),
                          torch.from_numpy(on[fit].astype(np.float32)))
    fit_generator = torch.Generator().manual_seed(seed)
    fit_l = DataLoader(fit_t, batch_size=tr.BATCH, shuffle=True, generator=fit_generator)
    val_l = None
    if val is not None:
        val_t = TensorDataset(torch.from_numpy(x[val]), torch.from_numpy(y[val]),
                              torch.from_numpy(on[val].astype(np.float32)))
        val_l = DataLoader(val_t, batch_size=tr.BATCH, shuffle=False)
    best = {"score": float("inf"), "epoch": 0}
    epoch_rng = np.random.default_rng(seed)
    for epoch in range(1, epochs + 1):
        reg.train(), det.train()
        # Bound runtime while rotating through source windows reproducibly.
        if len(fit) > WINDOWS_PER_EPOCH:
            take = epoch_rng.choice(len(fit), WINDOWS_PER_EPOCH, replace=False)
            batches = DataLoader(torch.utils.data.Subset(fit_t, take.tolist()),
                                 batch_size=tr.BATCH, shuffle=True,
                                 generator=torch.Generator().manual_seed(seed + epoch))
        else:
            batches = fit_l
        for xb, yb_w, ob in batches:
            xb, yb_w, ob = xb.to(tr.DEVICE), yb_w.to(tr.DEVICE), ob.to(tr.DEVICE)
            # Simulate modest aggregate meter calibration error and noise. Appliance targets and
            # calendar inputs stay unchanged; augmentation is applied only to training batches.
            gain = torch.empty((len(xb), 1, 1), device=tr.DEVICE).uniform_(*AGGREGATE_GAIN)
            noise = torch.randn_like(xb[:, :1]) * AGGREGATE_NOISE_STD_W
            xb = xb.clone()
            xb[:, :1] = (xb[:, :1] * gain + noise).clamp_min(0)
            yb = yb_w / scale_w
            y_hat = reg(tr.regressor_inputs(xb))
            logits = det(tr.detector_inputs(xb))
            ob_mask = ob
            loss_reg = (ob_mask * (y_hat - yb) ** 2).sum() / ob_mask.sum().clamp(min=1)
            gated = torch.sigmoid(logits) * y_hat.detach().clamp(min=0)
            loss_crit = F.mse_loss(gated, yb) + F.mse_loss(gated.mean(-1), yb.mean(-1))
            loss_cls = tr.classification_loss(logits, ob_mask, pos_weight)
            opt_r.zero_grad(set_to_none=True), opt_d.zero_grad(set_to_none=True)
            (loss_reg + loss_cls + tr.LAMBDA * loss_crit).backward()
            opt_r.step(), opt_d.step()
        if val_l is None:
            continue
        reg.eval(), det.eval()
        with torch.no_grad():
            score = float(np.mean([float(sum(tr.losses(reg, det, b, scale_w, pos_weight)))
                                   for b in val_l]))
        if score < best["score"]:
            best = {"score": score, "epoch": epoch,
                    "regressor": {k: v.detach().cpu().clone() for k, v in reg.state_dict().items()},
                    "detector": {k: v.detach().cpu().clone() for k, v in det.state_dict().items()}}
        print(f"  augmented seed {seed} epoch {epoch} source-val {score:.4f} (best {best['epoch']})",
              flush=True)
        if epoch - best["epoch"] >= PATIENCE:
            break
    if val_l is None:
        best = {"epoch": epochs,
                "regressor": {k: v.detach().cpu().clone() for k, v in reg.state_dict().items()},
                "detector": {k: v.detach().cpu().clone() for k, v in det.state_dict().items()}}
    return {
        "seed": seed, "best_epoch": best["epoch"], "best_score": best.get("score"),
        "scale_w": scale.tolist(), "detector_config": tr.asdict(det_cfg),
        "regressor_config": tr.asdict(reg_cfg), "detector_state": best["detector"],
        "regressor_state": best["regressor"],
    }


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def train_source(source: int) -> tuple[dict, dict]:
    labels = list(tr.CHANNELS[source])
    on_w = np.asarray([tr.ON_THRESHOLD_W[n] for n in labels], dtype=np.float32)
    x, y, start, end = tr.load(source)
    split = tr.split(start, end)
    fit = np.flatnonzero(split == "train")
    val = np.flatnonzero(split == "val")
    pretest = np.flatnonzero((split != "test") & (split != "cross"))
    if min(len(fit), len(val), len(pretest)) == 0:
        raise RuntimeError(f"House {source} lacks a train, validation, or pre-test partition")

    on = y >= on_w[None, :, None]
    det_cfg = tr.GRUConfig(c_in=x.shape[1] + 1, c_out=len(labels))
    reg_cfg = tr.NILMFormerConfig(c_out=len(labels))
    # Keep the deployed architecture while training for tolerance to aggregate
    # meter calibration drift and noise; all fitting/tuning stays source-house only.
    stage_a = [train_seed(x, y, on, s, fit, val, EPOCHS, det_cfg, reg_cfg) for s in SEEDS]
    best_epoch = int(np.median([m["best_epoch"] for m in stage_a]))
    p_val, _ = model_predict(stage_a, x[val])
    thresholds = val_thresholds(p_val.transpose(0, 2, 1).reshape(-1, len(labels)),
                                on[val].transpose(0, 2, 1).reshape(-1, len(labels)), labels)
    final = [train_seed(x, y, on, s, pretest, None, best_epoch, det_cfg, reg_cfg)
             for s in SEEDS]

    model_dir = VERSION / f"house{source}"
    model_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "model_version": "research-v1",
        "source_house": source,
        "architecture": {
            "detector": "GRUDetector",
            "regressor": "NILMFormerRegressor",
            "ensemble": "mean detector probabilities; median regressor power; soft probability gate",
            "input": "(B, 9, 256) float32: aggregate watts plus 8 wall-clock sine/cosine features",
            "output": "(B, C, 256) appliance watts",
        },
        "training": {
            "seeds": list(SEEDS),
            "seed_selection": "fixed in advance; two independently initialized members",
            "fit_partition": "train only for validation stage; all pre-test source windows including prior gap for final fit",
            "validation_partition": "source-house temporal val only",
            "epochs_cap": EPOCHS,
            "patience": PATIENCE,
            "selected_epochs": [m["best_epoch"] for m in stage_a],
            "final_epochs": best_epoch,
            "train_windows": int(len(fit)),
            "validation_windows": int(len(val)),
            "final_fit_windows": int(len(pretest)),
            "final_fit_through": str(end[pretest].max()),
            "thresholds": "per-label F1 maximization on source validation probabilities, grid 0.02..0.98",
            "augmentation": {
                "aggregate_gain_uniform": list(AGGREGATE_GAIN),
                "aggregate_gaussian_noise_std_w": AGGREGATE_NOISE_STD_W,
                "labels_and_calendar_features_unchanged": True,
            },
            "windows_per_epoch_cap": WINDOWS_PER_EPOCH,
            "event_thresholds": thresholds.tolist(),
        },
        "data_contract": {
            "preprocessing": "dataset.training.train_house.load; source-house only",
            "sample_seconds": int(tr.SAMPLE.total_seconds()),
            "window": tr.WINDOW,
            "labels": labels,
            "on_threshold_w": on_w.tolist(),
        },
        "seed_validation": {
            "source_house": source,
            "per_seed_best_epoch": [m["best_epoch"] for m in stage_a],
            "per_seed_best_loss": [m["best_score"] for m in stage_a],
        },
    }
    bundle = {
        "format": "wattprint-nilm/2",
        "appliances": list(tr.CHANNELS[source].values()),
        "labels": labels,
        "on_threshold_w": on_w.tolist(),
        "gate": "soft",
        "event_thresholds": thresholds.tolist(),
        "tau_w": tr.TAU_W,
        "sample_seconds": int(tr.SAMPLE.total_seconds()),
        "window": tr.WINDOW,
        "input": summary["architecture"]["input"],
        "output": summary["architecture"]["output"],
        "members": [{k: m[k] for k in (
            "seed", "scale_w", "detector_config", "regressor_config", "detector_state", "regressor_state"
        )} for m in final],
        "meta": summary,
    }
    checkpoint = model_dir / "nilm_pipeline.pt"
    torch.save(bundle, checkpoint)
    summary["checkpoint"] = checkpoint.name
    summary["checkpoint_sha256"] = sha256(checkpoint)
    (model_dir / "metadata.json").write_text(json.dumps(summary, indent=2) + "\n")
    del x, y, on
    print(f"house{source}: trained {len(final)} members x {best_epoch} epochs; saved {checkpoint}", flush=True)
    return bundle, summary


def main(max_windows: int) -> None:
    if max_windows < 1:
        raise ValueError("--max-windows must be positive")
    torch.set_num_threads(min(torch.get_num_threads(), 4))
    torch.use_deterministic_algorithms(True, warn_only=True)
    bundles, source_meta = {}, {}
    for source in SOURCES:
        bundles[source], source_meta[source] = train_source(source)

    # Target windows are accessed only after source checkpoints and thresholds are frozen.
    target_data, selection = {}, {}
    base_manifest = json.loads((ROOT / "dataset/research_v1/baseline/manifest.json").read_text())
    if max_windows != base_manifest["max_windows_per_target"]:
        raise ValueError("Use the baseline's max_windows value so paired windows stay identical")
    for target in TARGETS:
        x, y, start, end = tr.load(target)
        selected = held_out_indices(start, end, max_windows)
        expected = np.asarray(base_manifest["target_selection"][str(target)]["window_indices"])
        if not np.array_equal(selected, expected):
            raise RuntimeError(f"Held-out selection mismatch for target house {target}")
        timestamps = (start[selected].to_numpy()[:, None] +
                      np.arange(tr.WINDOW)[None, :] * tr.SAMPLE.to_timedelta64()).reshape(-1)
        target_data[target] = (x, y, selected, timestamps)
        selection[str(target)] = base_manifest["target_selection"][str(target)]

    rows: list[dict] = []
    prediction_manifest: dict[str, dict] = {}
    pred_dir = OUT / "predictions"
    pred_dir.mkdir(exist_ok=True)
    for target, (x, y, selected, timestamps) in target_data.items():
        for source in SOURCES:
            bundle = bundles[source]
            labels = [name for name in bundle["labels"] if name in tr.CHANNELS[target]]
            cols = [bundle["labels"].index(name) for name in labels]
            target_cols = [list(tr.CHANNELS[target]).index(name) for name in labels]
            p_all, pred_all = model_predict(bundle["members"], x[selected])
            true = y[selected][:, target_cols].transpose(0, 2, 1).reshape(-1, len(labels))
            predicted = pred_all[:, cols].transpose(0, 2, 1).reshape(-1, len(labels))
            probabilities = p_all[:, cols].transpose(0, 2, 1).reshape(-1, len(labels))
            kind = "in_house" if source == target else "cross_house"
            out_path = pred_dir / f"source{source}_target{target}.npz"
            thresholds = np.asarray(bundle["event_thresholds"])[cols]
            np.savez_compressed(
                out_path,
                house_id=np.int64(target), source_house_id=np.int64(source),
                evaluation_kind=np.asarray(kind), held_out_split=np.asarray("test"),
                timestamp=timestamps, aggregate_w=x[selected, 0].reshape(-1),
                y_true_w=true, y_pred_w=predicted, p_on=probabilities,
                labels=np.asarray(labels), sample_seconds=np.int64(tr.SAMPLE.total_seconds()),
                selected_window_indices=selected, event_thresholds=thresholds,
            )
            prediction_manifest[out_path.name] = {
                "source_house": source, "target_house": target,
                "target_split": "test", "window_indices": selected.tolist(),
                "labels": labels, "model_sha256": source_meta[source]["checkpoint_sha256"],
            }
            for j, label in enumerate(labels):
                kwh = tr.SAMPLE.total_seconds() / 3.6e6
                on = true[:, j] >= tr.ON_THRESHOLD_W[label]
                rows.append({
                    "model_version": "research-v1", "source_house": source,
                    "target_house": target, "evaluation_kind": kind,
                    "held_out_split": "test", "device": label,
                    "n_windows": len(selected), "n_samples": len(true),
                    "n_on_samples": int(on.sum()),
                    "true_kwh": float(true[:, j].sum() * kwh),
                    "predicted_kwh": float(predicted[:, j].sum() * kwh),
                    "signed_error_kwh": float((predicted[:, j].sum() - true[:, j].sum()) * kwh),
                    "absolute_error_kwh": float(abs(predicted[:, j].sum() - true[:, j].sum()) * kwh),
                    "absolute_percentage_error": (
                        float(abs(predicted[:, j].sum() - true[:, j].sum()) / true[:, j].sum() * 100)
                        if true[:, j].sum() > 1e-6 else None
                    ),
                    "f1_on_off": f1(on, probabilities[:, j] >= thresholds[j]),
                    "event_threshold": float(thresholds[j]),
                })
            print(f"{out_path.name}: {len(selected)} paired held-out windows", flush=True)
    with (OUT / "metrics.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    manifest = {
        "model_version": "research-v1",
        "command": "uv run --group nilm python dataset/research_v1/model/run.py --max-windows 128",
        "architecture": "GRUDetector + NILMFormerRegressor, two-member ensemble",
        "sources": list(SOURCES), "targets": list(TARGETS), "seeds": list(SEEDS),
        "training_metadata": {str(k): v for k, v in source_meta.items()},
        "paired_evaluation": {
            "selection_source": "dataset/research_v1/baseline/manifest.json",
            "held_out_split": "test", "target_tuning": "none",
            "target_selection": selection,
            "house6_freezer": "not compared with Fridge",
            "predictions": prediction_manifest,
        },
        "compatibility": "Checkpoint is wattprint-nilm/2 and loads with app.modules.nilm.services.engine.load; see README.md for exact input/output contract.",
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"saved {OUT / 'metrics.csv'}", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-windows", type=int, default=128)
    main(ap.parse_args().max_windows)
