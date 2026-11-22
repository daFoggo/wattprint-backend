"""Four-fold house-grouped dual-branch TCN NILM experiment.

Run from repository root: uv run --group nilm python dataset/research_v2/run.py
All learned choices for a fold use its three source houses only. The target
house is scored once after checkpoint and thresholds have been frozen.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from dataset.research_v2.architecture import LABELS, ModelConfig, TCNDetector, TCNRegressor  # noqa: E402
from dataset.training import train_house as tr  # noqa: E402

OUT = Path(__file__).resolve().parent
HOUSES = (2, 3, 5, 6)
SEEDS = (11, 22)
ON_W = np.array([tr.ON_THRESHOLD_W[label] for label in LABELS], dtype=np.float32)
POWER_SCALE_W = np.array([150, 1500, 1500, 1200, 1500, 2500], dtype=np.float32)


@dataclass
class House:
    x: np.ndarray
    y: np.ndarray
    mask: np.ndarray
    start: object
    end: object
    sample_weights: np.ndarray


def load_house(house: int) -> House:
    x, original_y, start, end = tr.load(house)
    y = np.zeros((len(x), len(LABELS), tr.WINDOW), dtype=np.float32)
    label_mask = np.zeros(len(LABELS), dtype=np.float32)
    for j, label in enumerate(LABELS):
        if label in tr.CHANNELS[house]:
            y[:, j] = original_y[:, list(tr.CHANNELS[house]).index(label)]
            label_mask[j] = 1.0
    present = y >= ON_W[None, :, None]
    any_on = present.any(axis=-1)
    frequency = any_on.mean(axis=0)
    bonus = np.minimum(3.0, 0.2 / np.sqrt(np.maximum(frequency, 1e-4)))
    weights = 1.0 + (any_on * bonus[None, :] * label_mask[None, :]).sum(axis=1)
    weights = weights / weights.sum()
    return House(x, y, label_mask, start, end, weights)


def sample_windows(houses: dict[int, House], ids: list[int], count: int, rng: np.random.Generator):
    """Uniform house quota; half uniform, half event-enriched windows per house."""
    arrays = []
    for house_id in ids:
        house = houses[house_id]
        n = count // len(ids)
        uniform = rng.integers(0, len(house.x), size=n // 2)
        enriched = rng.choice(len(house.x), size=n - len(uniform), p=house.sample_weights)
        selected = np.concatenate((uniform, enriched))
        arrays.append((house.x[selected], house.y[selected],
                       np.broadcast_to(house.mask[None, :], (len(selected), len(LABELS))).copy()))
    x = np.concatenate([a[0] for a in arrays])
    y = np.concatenate([a[1] for a in arrays])
    masks = np.concatenate([a[2] for a in arrays])
    permutation = rng.permutation(len(x))
    return x[permutation], y[permutation], masks[permutation]


def validation_windows(house: House, max_windows: int = 512):
    # Deterministic source-only validation with both uniform and event-enriched coverage.
    n = len(house.x)
    uniform = np.linspace(0, n - 1, min(max_windows // 2, n), dtype=np.int64)
    event_rank = np.argsort(-house.sample_weights, kind="stable")[: max_windows // 2]
    selected = np.unique(np.r_[uniform, event_rank])
    mask = np.broadcast_to(house.mask[None, :], (len(selected), len(LABELS))).copy()
    return house.x[selected], house.y[selected], mask


def batch_loss(detector, regressor, x, y_w, mask, pos_weight, scales):
    logits = detector(x)
    conditional = regressor(x)
    target = y_w / scales[None, :, None]
    on = (y_w >= torch.as_tensor(ON_W, device=x.device)[None, :, None]).float()
    valid = mask[:, :, None]
    denom = (valid.sum() * y_w.shape[-1]).clamp_min(1)
    bce = F.binary_cross_entropy_with_logits(logits, on, reduction="none",
                                              pos_weight=pos_weight[None, :, None])
    det_loss = (bce * valid).sum() / denom
    active = on * valid
    reg_loss = (F.smooth_l1_loss(conditional, target, beta=0.2, reduction="none") * active).sum() / active.sum().clamp_min(1)
    predicted = torch.sigmoid(logits) * conditional
    mixed_loss = (torch.abs(predicted - target) * valid).sum() / denom
    energy_loss = (torch.abs(predicted.mean(-1) - target.mean(-1)) * mask).sum() / mask.sum().clamp_min(1)
    return 2.0 * det_loss + reg_loss + mixed_loss + 0.5 * energy_loss


@torch.no_grad()
def predict_members(members: list[dict], x: np.ndarray, config: ModelConfig, device: torch.device):
    probabilities, powers = [], []
    for member in members:
        detector = TCNDetector(config).to(device)
        regressor = TCNRegressor(config).to(device)
        detector.load_state_dict(member["detector_state"])
        regressor.load_state_dict(member["regressor_state"])
        detector.eval(), regressor.eval()
        p_parts, a_parts = [], []
        for i in range(0, len(x), 64):
            xb = torch.from_numpy(x[i:i + 64]).to(device)
            p_parts.append(torch.sigmoid(detector(xb)).cpu().numpy())
            a_parts.append((regressor(xb) * torch.as_tensor(POWER_SCALE_W, device=device)[None, :, None]).cpu().numpy())
        probabilities.append(np.concatenate(p_parts))
        powers.append(np.concatenate(a_parts))
    p = np.mean(probabilities, axis=0)
    a = np.mean(powers, axis=0)
    return p, np.maximum(p * a, 0)


def f1(actual: np.ndarray, prediction: np.ndarray) -> float | None:
    tp = int((actual & prediction).sum())
    fp = int((~actual & prediction).sum())
    fn = int((actual & ~prediction).sum())
    return 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None


def choose_thresholds(prob: np.ndarray, y: np.ndarray, mask: np.ndarray):
    grid = np.linspace(0.05, 0.95, 19)
    thresholds = []
    for j in range(len(LABELS)):
        valid = mask[:, j] > 0
        actual = (y[valid, j] >= ON_W[j]).reshape(-1)
        scores = prob[valid, j].reshape(-1)
        if not actual.any():
            thresholds.append(0.5)
        else:
            values = [f1(actual, scores >= t) or 0.0 for t in grid]
            thresholds.append(float(grid[int(np.argmax(values))]))
    return np.asarray(thresholds, dtype=np.float32)


def train_seed(houses: dict[int, House], train_ids: list[int], val: tuple | None,
               seed: int, epochs: int, windows_per_epoch: int,
               config: ModelConfig, device: torch.device):
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    detector = TCNDetector(config).to(device)
    regressor = TCNRegressor(config).to(device)
    optimizer = torch.optim.AdamW(list(detector.parameters()) + list(regressor.parameters()), lr=8e-4, weight_decay=1e-3)
    # Class weights are estimated only from the houses in this fit partition.
    positives, totals = np.zeros(len(LABELS)), np.zeros(len(LABELS))
    for house_id in train_ids:
        h = houses[house_id]
        positives += ((h.y >= ON_W[None, :, None]).sum(axis=(0, 2)) * h.mask)
        totals += len(h.x) * tr.WINDOW * h.mask
    prevalence = positives / np.maximum(totals, 1)
    pos_weight = torch.tensor(np.clip(np.sqrt((1 - prevalence) / np.maximum(prevalence, 1e-5)), 1, 20), dtype=torch.float32, device=device)
    scales = torch.tensor(POWER_SCALE_W, dtype=torch.float32, device=device)
    best = {"loss": float("inf"), "epoch": 0}
    history = []
    for epoch in range(1, epochs + 1):
        detector.train(), regressor.train()
        x, y, mask = sample_windows(houses, train_ids, windows_per_epoch, rng)
        train_losses = []
        for i in range(0, len(x), 32):
            xb = torch.from_numpy(x[i:i + 32]).to(device)
            yb = torch.from_numpy(y[i:i + 32]).to(device)
            mb = torch.from_numpy(mask[i:i + 32]).to(device)
            optimizer.zero_grad(set_to_none=True)
            loss = batch_loss(detector, regressor, xb, yb, mb, pos_weight, scales)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(list(detector.parameters()) + list(regressor.parameters()), 5.0)
            optimizer.step()
            train_losses.append(float(loss.detach()))
        value = float(np.mean(train_losses))
        if val is not None:
            detector.eval(), regressor.eval()
            vx, vy, vm = val
            losses = []
            with torch.no_grad():
                for i in range(0, len(vx), 64):
                    xb = torch.from_numpy(vx[i:i + 64]).to(device)
                    yb = torch.from_numpy(vy[i:i + 64]).to(device)
                    mb = torch.from_numpy(vm[i:i + 64]).to(device)
                    losses.append(float(batch_loss(detector, regressor, xb, yb, mb, pos_weight, scales)))
            value = float(np.mean(losses))
        history.append({"epoch": epoch, "train_loss": float(np.mean(train_losses)), "val_loss": value if val is not None else None})
        if value < best["loss"]:
            best = {"loss": value, "epoch": epoch,
                    "detector_state": {k: v.detach().cpu().clone() for k, v in detector.state_dict().items()},
                    "regressor_state": {k: v.detach().cpu().clone() for k, v in regressor.state_dict().items()}}
        print(f"  seed {seed} epoch {epoch}: train {np.mean(train_losses):.4f} val {value:.4f}", flush=True)
        if val is not None and epoch - best["epoch"] >= 3:
            break
    return {"seed": seed, "best_epoch": best["epoch"], "best_loss": best["loss"],
            "detector_state": best["detector_state"], "regressor_state": best["regressor_state"],
            "history": history}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--epochs", type=int, default=10)
    parser.add_argument("--windows-per-epoch", type=int, default=384)
    parser.add_argument("--folds", type=int, nargs="+", default=list(HOUSES))
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    args = parser.parse_args()
    if args.epochs < 1 or args.windows_per_epoch < 32:
        parser.error("epochs must be positive and windows-per-epoch >= 32")
    torch.set_num_threads(4)
    cuda_free = torch.cuda.mem_get_info()[0] if torch.cuda.is_available() else 0
    device = torch.device("cuda" if args.device == "cuda" or
                          (args.device == "auto" and cuda_free >= 4 * 1024**3) else "cpu")
    print(f"training device: {device} (CUDA free {cuda_free / 1024**3:.2f} GiB)", flush=True)
    config = ModelConfig()
    houses = {h: load_house(h) for h in HOUSES}
    base_manifest = json.loads((ROOT / "dataset/research_v1/baseline/manifest.json").read_text())
    rows, fold_meta = [], {}
    (OUT / "weights").mkdir(parents=True, exist_ok=True)
    (OUT / "predictions").mkdir(parents=True, exist_ok=True)
    for target in args.folds:
        if target not in HOUSES:
            parser.error(f"unknown fold {target}")
        sources = [h for h in HOUSES if h != target]
        val_house = next(h for h in sources if h != 6)
        fit_houses = [h for h in sources if h != val_house]
        val = validation_windows(houses[val_house])
        print(f"fold target {target}: inner train {fit_houses}, validation house {val_house}; outer fit {sources}", flush=True)
        stage_a = [train_seed(houses, fit_houses, val, seed, args.epochs, args.windows_per_epoch, config, device)
                   for seed in SEEDS]
        p_val, _ = predict_members(stage_a, val[0], config, device)
        thresholds = choose_thresholds(p_val, val[1], val[2])
        final_epochs = int(np.median([m["best_epoch"] for m in stage_a]))
        final = [train_seed(houses, sources, None, seed, final_epochs, args.windows_per_epoch, config, device)
                 for seed in SEEDS]
        payload = {"format": "wattprint-nilm-tcn/1", "version": "research-v2.0.0",
                   "config": config.to_dict(), "labels": list(LABELS),
                   "on_threshold_w": ON_W.tolist(), "power_scale_w": POWER_SCALE_W.tolist(),
                   "event_thresholds": thresholds.tolist(), "sample_seconds": 15, "window": 256,
                   "members": [{k: m[k] for k in ("seed", "detector_state", "regressor_state")} for m in final],
                   "training": {"outer_target_house": target, "outer_source_houses": sources,
                                "inner_validation_house": val_house, "inner_fit_houses": fit_houses,
                                "seeds": list(SEEDS), "best_epochs": [m["best_epoch"] for m in stage_a],
                                "final_epochs": final_epochs, "epochs_cap": args.epochs,
                                "windows_per_epoch": args.windows_per_epoch,
                                "threshold_rule": "maximize inner grouped-validation F1 per label on 0.05..0.95 grid"}}
        path = OUT / "weights" / f"loho_target{target}_v2.0.0.pt"
        torch.save(payload, path)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        # Only now open target arrays for scoring; no target statistic entered the fit.
        h = houses[target]
        selected = np.asarray(base_manifest["target_selection"][str(target)]["window_indices"], dtype=np.int64)
        p, watts = predict_members(final, h.x[selected], config, device)
        comparable = [j for j, label in enumerate(LABELS) if h.mask[j]]
        labels = np.asarray([LABELS[j] for j in comparable])
        y_true = h.y[selected][:, comparable].transpose(0, 2, 1).reshape(-1, len(comparable))
        y_pred = watts[:, comparable].transpose(0, 2, 1).reshape(-1, len(comparable))
        p_on = p[:, comparable].transpose(0, 2, 1).reshape(-1, len(comparable))
        timestamps = (h.start[selected].to_numpy()[:, None] +
                      np.arange(256)[None, :] * np.timedelta64(15, "s")).reshape(-1)
        np.savez_compressed(OUT / "predictions" / f"loho_target{target}.npz",
                            house_id=np.int64(target), timestamp=timestamps,
                            aggregate_w=h.x[selected, 0].reshape(-1), y_true_w=y_true,
                            y_pred_w=y_pred, p_on=p_on, labels=labels,
                            event_thresholds=thresholds[comparable], sample_seconds=np.int64(15),
                            selected_window_indices=selected)
        for c, label in enumerate(labels):
            truth, pred = y_true[:, c], y_pred[:, c]
            true_on = truth >= ON_W[comparable[c]]
            tkwh, pkwh = truth.sum() * 15 / 3.6e6, pred.sum() * 15 / 3.6e6
            rows.append({"target_house": target, "device": label, "samples": len(truth),
                         "on_samples": int(true_on.sum()), "true_kwh": float(tkwh),
                         "predicted_kwh": float(pkwh), "signed_error_kwh": float(pkwh - tkwh),
                         "absolute_error_kwh": float(abs(pkwh - tkwh)),
                         "absolute_percentage_error": float(100 * abs(pkwh - tkwh) / tkwh) if tkwh > 1e-12 else None,
                         "f1_on_off": f1(true_on, p_on[:, c] >= thresholds[comparable[c]]),
                         "event_threshold": float(thresholds[comparable[c]])})
        fold_meta[str(target)] = {"checkpoint": str(path.relative_to(OUT)), "sha256": digest,
                                  "prediction": f"predictions/loho_target{target}.npz",
                                  "training": payload["training"]}
        print(f"saved fold {target} checkpoint, {len(selected)} held-out windows", flush=True)
    with (OUT / "metrics.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader(), writer.writerows(rows)
    (OUT / "manifest.json").write_text(json.dumps({"version": "research-v2.0.0", "folds": fold_meta,
        "command": f"uv run --group nilm python dataset/research_v2/run.py --epochs {args.epochs} --windows-per-epoch {args.windows_per_epoch}",
        "protocol": "grouped inner validation, outer leave-one-house-out, frozen target-independent thresholds",
        "baseline_window_manifest": "dataset/research_v1/baseline/manifest.json"}, indent=2) + "\n")


if __name__ == "__main__":
    main()
