"""Build a prespecified equal-source House2/House5 blend for unseen Houses 3/6."""
from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
OUT = HERE / "v2_source_blend"


def f1(t: np.ndarray, p: np.ndarray) -> float | None:
    tp = int(np.count_nonzero(t & p))
    fp = int(np.count_nonzero(~t & p))
    fn = int(np.count_nonzero(t & ~p))
    return 2 * tp / (2 * tp + fp + fn) if tp + fn else None


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    weights = OUT / "weights"
    weights.mkdir(exist_ok=True)
    thresholds_by_source = {}
    for source in (2, 5):
        source_path = ROOT / f"dataset/models/nilm/house{source}/nilm_pipeline.pt"
        copy_path = weights / f"house{source}.pt"
        shutil.copy2(source_path, copy_path)
        thresholds_by_source[source] = torch.load(
            copy_path, map_location="cpu", weights_only=True
        )["event_thresholds"]
    rows, outputs = [], {}
    for target in (3, 6):
        a = np.load(ROOT / "dataset/research_v1/baseline" / f"source2_target{target}.npz")
        b = np.load(ROOT / "dataset/research_v1/baseline" / f"source5_target{target}.npz")
        labels_a, labels_b = a["labels"].tolist(), b["labels"].tolist()
        labels = [name for name in labels_a if name in labels_b]
        ia, ib = [labels_a.index(v) for v in labels], [labels_b.index(v) for v in labels]
        if not np.array_equal(a["timestamp"], b["timestamp"]):
            raise ValueError(f"source windows differ for target {target}")
        if not np.array_equal(a["y_true_w"][:, ia], b["y_true_w"][:, ib]):
            raise ValueError(f"source truth differs for target {target}")
        # Equal source weight is fixed before inspecting these held-out targets.
        pred = 0.5 * (a["y_pred_w"][:, ia] + b["y_pred_w"][:, ib])
        la, lb = a["labels"].tolist(), b["labels"].tolist()
        ta = np.asarray([thresholds_by_source[2][la.index(n)] for n in labels])
        tb = np.asarray([thresholds_by_source[5][lb.index(n)] for n in labels])
        score = 0.5 * (a["p_on"][:, ia] / ta[None, :] + b["p_on"][:, ib] / tb[None, :])
        score_probability = score / (1.0 + score)
        truth = a["y_true_w"][:, ia]
        thresholds = np.asarray([0.5] * len(labels), dtype=np.float32)
        path = OUT / f"blend2_5_target{target}.npz"
        np.savez_compressed(
            path,
            house_id=a["house_id"], source_house_id=np.asarray("2+5"),
            evaluation_kind=np.asarray("cross_house_ensemble"),
            held_out_split=np.asarray("test"), timestamp=a["timestamp"],
            aggregate_w=a["aggregate_w"], y_true_w=truth, y_pred_w=pred,
            # score/(1+score) makes score >= 1 equivalent to p_on >= 0.5.
            p_on=score_probability, labels=np.asarray(labels), sample_seconds=a["sample_seconds"],
            selected_window_indices=a["selected_window_indices"], event_thresholds=thresholds,
        )
        outputs[path.name] = {
            "sources": [2, 5], "source_weight": 0.5,
            "target_house": target, "held_out_split": "test",
            "labels": labels,
            "on_rule": "mean(p_on_source / source_validation_threshold) >= 1; stored p_on=score/(1+score), cutoff 0.5",
            "power_rule": "0.5 * source2_watts + 0.5 * source5_watts",
        }
        for j, label in enumerate(labels):
            t, p = truth[:, j], pred[:, j]
            on = t >= {"Fridge": 50, "Freezer": 50, "WashMach": 20,
                      "Dishwash": 10, "Microwave": 200, "Toaster": 200,
                      "Kettle": 1000}[label]
            kwh = 15 / 3.6e6
            err = float((p.sum() - t.sum()) * kwh)
            rows.append({
                "model_version": "v2_source_blend", "source_house": "2+5",
                "target_house": target, "evaluation_kind": "cross_house_ensemble",
                "held_out_split": "test", "device": label,
                "n_windows": int(len(a["selected_window_indices"])),
                "n_samples": int(len(t)), "n_on_samples": int(on.sum()),
                "true_kwh": float(t.sum() * kwh), "predicted_kwh": float(p.sum() * kwh),
                "signed_error_kwh": err, "absolute_error_kwh": abs(err),
                "absolute_percentage_error": abs(err) / float(t.sum() * kwh) * 100
                if t.sum() > 1e-6 else None,
                "f1_on_off": f1(on, score_probability[:, j] >= 0.5),
                "event_threshold": 0.5,
            })
    with (OUT / "metrics.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    manifest = {
        "model_version": "v2_source_blend",
        "purpose": "fixed equal-weight source-model blend evaluated only on unseen Houses 3 and 6",
        "source_checkpoints": {
            "2": "weights/house2.pt",
            "5": "weights/house5.pt",
        },
        "training": "none; blend references frozen source checkpoints",
        "selection": "equal source weights and normalized-threshold decision fixed before target evaluation",
        "output_contract": "wattprint-nilm/2 source bundles; equal raw-watt mean, ON decision mean(p_on/source threshold)>=1; p_on stored as score/(1+score) with cutoff .5",
        "source_event_thresholds": {str(k): list(v) for k, v in thresholds_by_source.items()},
        "predictions": outputs,
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"wrote {len(rows)} device rows to {OUT / 'metrics.csv'}")


if __name__ == "__main__":
    main()
