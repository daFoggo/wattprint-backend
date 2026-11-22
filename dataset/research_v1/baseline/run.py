"""Evaluate saved House 2/5 NILM bundles on held-out REFIT windows.

Each target house has one deterministic temporal test selection shared by both
source bundles. This makes the in-house and cross-house predictions directly
comparable on identical windows. Run from the repository root:

    uv run python dataset/research_v1/baseline/run.py --max-windows 128
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from dataset.training.train_house import CHANNELS, ON_THRESHOLD_W, SAMPLE, WINDOW, load, predict, split  # noqa: E402

OUT = Path(__file__).resolve().parent
SOURCES = (2, 5)
TARGETS = (2, 3, 5, 6)


def f1(t: np.ndarray, p: np.ndarray) -> float | None:
    tp = int(np.count_nonzero(t & p))
    fp = int(np.count_nonzero(~t & p))
    fn = int(np.count_nonzero(t & ~p))
    return 2 * tp / (2 * tp + fp + fn) if tp + fn else None


def held_out_indices(start, end, max_windows: int) -> np.ndarray:
    """Evenly sample the target house's temporal test partition, independent of model."""
    eligible = np.flatnonzero(split(start, end) == "test")
    if not len(eligible):
        raise RuntimeError("No eligible held-out test windows")
    # Integer linspace includes both ends and is deterministic across platforms.
    positions = np.unique(np.linspace(0, len(eligible) - 1,
                                     min(max_windows, len(eligible)), dtype=np.int64))
    return eligible[positions]


def main(max_windows: int) -> None:
    if max_windows < 1:
        raise ValueError("--max-windows must be positive")
    torch.set_num_threads(4)
    rows: list[dict] = []
    target_manifest: dict[str, dict] = {}

    # Load and select once per target so each source bundle sees exactly the same
    # held-out windows, including for source/target pairs that are cross-house.
    for target in TARGETS:
        x, y, start, end = load(target)
        selected = held_out_indices(start, end, max_windows)
        timestamps = (start[selected].to_numpy()[:, None] +
                      np.arange(WINDOW)[None, :] * SAMPLE.to_timedelta64()).reshape(-1)
        target_manifest[str(target)] = {
            "held_out_split": "test",
            "window_indices": selected.tolist(),
            "window_start_timestamps": [str(v) for v in start[selected].to_numpy()],
            "window_end_timestamps": [str(v) for v in end[selected].to_numpy()],
            "selected_window_count": int(len(selected)),
            "timestamp_count": int(len(timestamps)),
        }

        for source in SOURCES:
            bundle_path = ROOT / f"dataset/models/nilm/house{source}/nilm_pipeline.pt"
            bundle = torch.load(bundle_path, map_location="cpu", weights_only=True)

            # House 6's Freezer is a distinct appliance and must not be scored as
            # Fridge. Only labels present in both the bundle and target are valid.
            labels = [name for name in bundle["labels"] if name in CHANNELS[target]]
            if not labels:
                raise RuntimeError(f"No comparable labels for source {source}, target {target}")
            model_columns = [bundle["labels"].index(name) for name in labels]
            truth_columns = [list(CHANNELS[target]).index(name) for name in labels]

            p_on_all, pred_all = predict(bundle["members"], x[selected])
            true = y[selected][:, truth_columns].transpose(0, 2, 1).reshape(-1, len(labels))
            predicted = pred_all[:, model_columns].transpose(0, 2, 1).reshape(-1, len(labels))
            probabilities = p_on_all[:, model_columns].transpose(0, 2, 1).reshape(-1, len(labels))
            aggregate = x[selected, 0].reshape(-1)
            kind = "in_house" if source == target else "cross_house"
            file = OUT / f"source{source}_target{target}.npz"
            np.savez_compressed(
                file,
                house_id=np.int64(target),
                source_house_id=np.int64(source),
                evaluation_kind=np.asarray(kind),
                held_out_split=np.asarray("test"),
                timestamp=timestamps,
                aggregate_w=aggregate,
                y_true_w=true,
                y_pred_w=predicted,
                p_on=probabilities,
                event_thresholds=np.asarray(bundle["event_thresholds"])[model_columns],
                labels=np.asarray(labels),
                sample_seconds=np.int64(SAMPLE.total_seconds()),
                selected_window_indices=selected,
            )

            for j, label in enumerate(labels):
                kwh = SAMPLE.total_seconds() / 3.6e6
                true_kwh = float(true[:, j].sum() * kwh)
                predicted_kwh = float(predicted[:, j].sum() * kwh)
                on = true[:, j] >= ON_THRESHOLD_W[label]
                threshold = bundle["event_thresholds"][bundle["labels"].index(label)]
                rows.append({
                    "source_house": source,
                    "target_house": target,
                    "evaluation_kind": kind,
                    "held_out_split": "test",
                    "device": label,
                    "n_windows": int(len(selected)),
                    "n_samples": int(len(true)),
                    "n_on_samples": int(on.sum()),
                    "true_kwh": true_kwh,
                    "predicted_kwh": predicted_kwh,
                    "signed_error_kwh": predicted_kwh - true_kwh,
                    "absolute_error_kwh": abs(predicted_kwh - true_kwh),
                    "absolute_percentage_error": (
                        100 * abs(predicted_kwh - true_kwh) / true_kwh
                        if true_kwh > 1e-6 else None
                    ),
                    "f1_on_off": f1(on, probabilities[:, j] >= threshold),
                })
            print(f"{file.name}: {len(selected)} held-out windows, {len(labels)} labels", flush=True)
        del x, y

    with (OUT / "metrics.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    manifest = {
        "command": (
            "uv run python dataset/research_v1/baseline/run.py "
            f"--max-windows {max_windows}"
        ),
        "max_windows_per_target": max_windows,
        "selection": (
            "For every target house, choose evenly spaced window indices from the temporal test "
            "partition defined by dataset.training.train_house.split; the same ordered indices "
            "are used for every source model evaluated on that target."
        ),
        "seed": None,
        "window_samples": WINDOW,
        "sample_seconds": int(SAMPLE.total_seconds()),
        "sources": list(SOURCES),
        "targets": list(TARGETS),
        "target_selection": target_manifest,
        "evaluation": {
            "in_house": "source house equals target house; target temporal test windows",
            "cross_house": "source differs from target; the same target temporal test windows",
        },
        "house6_freezer": "not comparable to Fridge; excluded from all model comparisons",
        "bundle_format": "wattprint-nilm/2",
        "outputs": {
            "predictions": "source{source}_target{target}.npz",
            "metrics": "metrics.csv",
        },
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-windows", type=int, default=128)
    main(parser.parse_args().max_windows)
