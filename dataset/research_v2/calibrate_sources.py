"""Source-group calibration of the two frozen production NILM bundles.

House2 bundle is calibrated on held-out House5 windows, and vice versa. The
calibrated bundles are evaluated only on Houses3 and6, which are unseen by
both fit and calibration. This optimizes detector cutoffs and regressor scale
without changing their backbones or touching production checkpoints.
"""
from __future__ import annotations

import csv
import hashlib
import json
import shutil
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "dataset/research_v1/baseline"
OUT = Path(__file__).resolve().parent / "v2_2_source_calibrated"
ON_W = {"Fridge": 50, "WashMach": 20, "Dishwash": 10,
        "Microwave": 200, "Toaster": 200, "Kettle": 1000}


def f1(a, p):
    tp, fp, fn = int((a & p).sum()), int((~a & p).sum()), int((a & ~p).sum())
    return 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None


def read(path):
    with np.load(path, allow_pickle=False) as z:
        return {k: z[k] for k in z.files}


def fit(cal: dict):
    labels = cal["labels"].astype(str).tolist()
    thresholds, scales, counts = [], [], []
    grid = np.linspace(0.05, 0.95, 19)
    for c, label in enumerate(labels):
        actual = cal["y_true_w"][:, c] >= ON_W[label]
        score = cal["p_on"][:, c]
        candidates = [f1(actual, score >= t) or 0 for t in grid]
        thresholds.append(float(grid[int(np.argmax(candidates))]) if actual.any() else 0.5)
        true_kwh = float(cal["y_true_w"][:, c].sum())
        predicted_kwh = float(cal["y_pred_w"][:, c].sum())
        # Fixed half-strength log shrinkage toward the identity adjustment.
        ratio = true_kwh / max(predicted_kwh, 1e-6)
        scales.append(float(np.clip(np.sqrt(ratio), 0.5, 2.0)))
        counts.append(int(actual.sum()))
    return np.asarray(thresholds, np.float32), np.asarray(scales, np.float32), counts


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "weights").mkdir(exist_ok=True)
    (OUT / "predictions").mkdir(exist_ok=True)
    rows, meta = [], {}
    for source, calibration_house in ((2, 5), (5, 2)):
        calibration = read(BASE / f"source{source}_target{calibration_house}.npz")
        thresholds, scales, counts = fit(calibration)
        source_checkpoint = ROOT / f"dataset/models/nilm/house{source}/nilm_pipeline.pt"
        copied = OUT / "weights" / f"house{source}.pt"
        shutil.copy2(source_checkpoint, copied)
        meta[str(source)] = {"calibration_house": calibration_house,
                             "calibration_window_count": int(len(calibration["selected_window_indices"])),
                             "on_positive_counts": counts,
                             "labels": calibration["labels"].astype(str).tolist(),
                             "event_thresholds": thresholds.tolist(), "power_scale": scales.tolist(),
                             "checkpoint": f"weights/house{source}.pt",
                             "checkpoint_sha256": hashlib.sha256(copied.read_bytes()).hexdigest()}
        for target in (3, 6):
            z = read(BASE / f"source{source}_target{target}.npz")
            labels = z["labels"].astype(str).tolist()
            idx = [meta[str(source)]["labels"].index(label) for label in labels]
            power = z["y_pred_w"] * scales[idx][None, :]
            events = thresholds[idx]
            out_path = OUT / "predictions" / f"source{source}_target{target}.npz"
            z["y_pred_w"] = power
            z["event_thresholds"] = events
            z["model_version"] = np.asarray("v2.2_source_calibrated")
            np.savez_compressed(out_path, **z)
            for c, label in enumerate(labels):
                truth = z["y_true_w"][:, c]
                true_on = truth >= ON_W[label]
                tkwh, pkwh = truth.sum() * 15 / 3.6e6, power[:, c].sum() * 15 / 3.6e6
                rows.append({"source_house": source, "calibration_house": calibration_house,
                             "target_house": target, "device": label, "samples": len(truth),
                             "on_samples": int(true_on.sum()), "true_kwh": float(tkwh),
                             "predicted_kwh": float(pkwh), "signed_error_kwh": float(pkwh - tkwh),
                             "absolute_error_kwh": float(abs(pkwh - tkwh)),
                             "f1_on_off": f1(true_on, z["p_on"][:, c] >= events[c])})
    with (OUT / "metrics.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader(), writer.writerows(rows)
    (OUT / "metadata.json").write_text(json.dumps({"version": "v2.2_source_calibrated", "sources": meta,
        "threshold_grid": "0.05..0.95 step 0.05, source-other-house F1 maximum",
        "power_adjustment": "sqrt(true energy / predicted energy), clipped 0.5..2.0",
        "targets": [3, 6], "target_data_used_for_calibration": False,
        "command": "uv run --group nilm python dataset/research_v2/calibrate_sources.py"}, indent=2) + "\n")
    print(f"wrote {len(rows)} device rows")


if __name__ == "__main__":
    main()
