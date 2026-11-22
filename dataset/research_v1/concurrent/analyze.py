#!/usr/bin/env python3
"""Measure NILM performance by the number of appliances concurrently ON.

Baseline use:
    uv run python dataset/research_v1/concurrent/analyze.py

To compare a later prediction directory against baseline on identical windows:
    uv run python dataset/research_v1/concurrent/analyze.py \
      --reference-dir dataset/research_v1/baseline \
      --candidate-dir dataset/research_v1/improved

The NPZ files must have the baseline runner's source{source}_target{target}.npz
names and aligned timestamp, truth, aggregate, and label arrays. Results are
written beside this script unless --output-dir is supplied.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BASELINE = ROOT / "dataset/research_v1/baseline"
ON_W = {
    "Fridge": 50.0, "Freezer": 50.0, "WashMach": 20.0,
    "Dishwash": 10.0, "Microwave": 200.0, "Toaster": 200.0,
    "Kettle": 1000.0,
}
# Frozen thresholds from the source-house wattprint-nilm/2 bundles used to
# generate baseline p_on. Retained here so this analysis is reproducible when
# the model files are unavailable.
EVENT_THRESHOLDS = {
    2: {"Fridge": .36, "WashMach": .18, "Dishwash": .46,
        "Microwave": .18, "Toaster": .32, "Kettle": .38},
    5: {"Fridge": .48, "WashMach": .10, "Dishwash": .30,
        "Microwave": .20, "Toaster": .24, "Kettle": .60},
}
WINDOW = 256


def _scalar(z: Any, key: str) -> Any:
    a = np.asarray(z[key])
    if a.size != 1:
        raise ValueError(f"{key} must be scalar")
    return a.reshape(()).item()


def _read(path: Path) -> dict[str, Any]:
    with np.load(path, allow_pickle=False) as z:
        required = {"timestamp", "aggregate_w", "y_true_w", "y_pred_w", "labels", "sample_seconds"}
        missing = required - set(z.files)
        if missing:
            raise ValueError(f"{path}: missing {sorted(missing)}")
        d = {k: np.array(z[k]) for k in required if k != "sample_seconds"}
        d["labels"] = d["labels"].astype(str).reshape(-1)
        d["sample_seconds"] = float(_scalar(z, "sample_seconds"))
        n, c = d["y_true_w"].shape
        if d["y_pred_w"].shape != (n, c) or len(d["labels"]) != c:
            raise ValueError(f"{path}: inconsistent truth/prediction/labels shapes")
        for key in ("timestamp", "aggregate_w"):
            d[key] = d[key].reshape(-1)
            if len(d[key]) != n:
                raise ValueError(f"{path}: {key} length does not match N={n}")
        if "p_on" in z.files:
            d["p_on"] = np.array(z["p_on"], dtype=float)
            if d["p_on"].shape != (n, c):
                raise ValueError(f"{path}: p_on shape mismatch")
        else:
            d["p_on"] = None
        if "event_thresholds" in z.files:
            d["event_thresholds"] = np.asarray(z["event_thresholds"], dtype=float).reshape(-1)
        else:
            d["event_thresholds"] = None
        d["source_house"] = int(_scalar(z, "source_house_id")) if "source_house_id" in z.files else int(path.name[6])
        d["target_house"] = int(_scalar(z, "house_id")) if "house_id" in z.files else int(path.name.split("target", 1)[1][0])
        d["selected_window_indices"] = np.array(z["selected_window_indices"]) if "selected_window_indices" in z.files else None
    if n == 0 or not np.isfinite(d["y_true_w"]).all() or not np.isfinite(d["y_pred_w"]).all():
        raise ValueError(f"{path}: empty or non-finite power data")
    return d


def event_thresholds(d: dict[str, Any]) -> np.ndarray:
    if d["event_thresholds"] is not None:
        t = d["event_thresholds"]
        if t.size == 1:
            return np.repeat(t, len(d["labels"]))
        if t.shape == (len(d["labels"]),):
            return t
        raise ValueError("event_thresholds must be scalar or one per label")
    by_label = EVENT_THRESHOLDS.get(d["source_house"], {})
    return np.array([by_label.get(str(label), .5) for label in d["labels"]], dtype=float)


def f1(actual: np.ndarray, predicted: np.ndarray) -> float | None:
    tp = int(np.count_nonzero(actual & predicted))
    fp = int(np.count_nonzero(~actual & predicted))
    fn = int(np.count_nonzero(actual & ~predicted))
    den = 2 * tp + fp + fn
    return 2 * tp / den if den else None


def strata(concurrent: np.ndarray) -> list[tuple[str, np.ndarray]]:
    return [(str(k), concurrent == k) for k in (0, 1, 2)] + [("3+", concurrent >= 3)]


def _metric(d: dict[str, Any], mask: np.ndarray, c: int, threshold: float,
            event_threshold: float) -> dict[str, Any]:
    dt = d["sample_seconds"]
    truth, pred = d["y_true_w"][mask, c], d["y_pred_w"][mask, c]
    truth_kwh = float(truth.sum() * dt / 3_600_000)
    pred_kwh = float(pred.sum() * dt / 3_600_000)
    a_on = truth >= threshold
    if d["p_on"] is not None:
        p_on = d["p_on"][mask, c] >= event_threshold
    else:
        p_on = pred >= threshold
    return {
        "sample_count": int(mask.sum()), "actual_on_samples": int(a_on.sum()),
        "true_kwh": truth_kwh, "predicted_kwh": pred_kwh,
        "signed_error_kwh": pred_kwh - truth_kwh,
        "absolute_error_kwh": abs(pred_kwh - truth_kwh),
        "absolute_percentage_error": 100 * abs(pred_kwh - truth_kwh) / truth_kwh if truth_kwh > 1e-12 else None,
        "f1_on_off": f1(a_on, p_on),
    }


def _assert_aligned(reference: dict[str, Any], candidate: dict[str, Any], ref_path: Path, cand_path: Path) -> None:
    for k in ("timestamp", "aggregate_w", "y_true_w"):
        if reference[k].shape != candidate[k].shape or not np.array_equal(reference[k], candidate[k]):
            raise ValueError(f"not same windows ({k} differs): {ref_path} vs {cand_path}")
    if not np.array_equal(reference["labels"], candidate["labels"]):
        raise ValueError(f"not same label order: {ref_path} vs {cand_path}")
    if not math.isclose(reference["sample_seconds"], candidate["sample_seconds"]):
        raise ValueError(f"sample_seconds differs: {ref_path} vs {cand_path}")


def _window_timestamp(values: np.ndarray, start: int) -> str:
    value = values[start]
    if np.issubdtype(values.dtype, np.datetime64):
        return str(value)
    return str(value)


def analyze_one(d: dict[str, Any], model_name: str, errors_limit: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    thresholds = np.array([ON_W[str(label)] for label in d["labels"]])
    on = d["y_true_w"] >= thresholds[None, :]
    concurrent = on.sum(axis=1)
    cuts = strata(concurrent)
    dt = d["sample_seconds"]
    n = len(concurrent)
    window_starts = np.arange(0, n, WINDOW)
    if n % WINDOW:
        raise ValueError(f"expected whole 256-step windows, found N={n}")
    metrics: list[dict[str, Any]] = []
    counts: list[dict[str, Any]] = []
    et = event_thresholds(d)
    for name, mask in cuts:
        counts.append({
            "model": model_name, "source_house": d["source_house"], "target_house": d["target_house"],
            "stratum": "actual_concurrent_on", "stratum_value": name,
            "sample_count": int(mask.sum()), "window_count_with_any_samples": int(sum(mask[a:a + WINDOW].any() for a in window_starts)),
        })
        for c, label in enumerate(d["labels"]):
            m = _metric(d, mask, c, thresholds[c], et[c])
            metrics.append({"model": model_name, "source_house": d["source_house"], "target_house": d["target_house"],
                            "evaluation_kind": "in_house" if d["source_house"] == d["target_house"] else "cross_house",
                            "stratum": "actual_concurrent_on", "stratum_value": name, "device": str(label),
                            "on_threshold_w": thresholds[c], "event_threshold": et[c], **m})

    # Rank each window/device high-error pair by absolute energy error. Keep
    # onset mismatch and power-amplitude error visible as separate classes.
    cases = []
    for w, start in enumerate(window_starts):
        stop = start + WINDOW
        sample_conc = concurrent[start:stop]
        majority = int(np.bincount(sample_conc, minlength=4).argmax())
        max_conc = int(sample_conc.max())
        for c, label in enumerate(d["labels"]):
            yt, yp = d["y_true_w"][start:stop, c], d["y_pred_w"][start:stop, c]
            a_on = yt >= thresholds[c]
            p_on = (d["p_on"][start:stop, c] >= et[c]) if d["p_on"] is not None else yp >= thresholds[c]
            true_kwh = float(yt.sum() * dt / 3_600_000)
            pred_kwh = float(yp.sum() * dt / 3_600_000)
            delta = pred_kwh - true_kwh
            if np.any(a_on & ~p_on) and np.any(p_on & ~a_on):
                category = "missed_and_false_on"
            elif np.any(a_on & ~p_on):
                category = "missed_on"
            elif np.any(p_on & ~a_on):
                category = "false_on"
            elif delta < 0:
                category = "amplitude_underestimate"
            elif delta > 0:
                category = "amplitude_overestimate"
            else:
                category = "matched"
            cases.append({
                "model": model_name, "source_house": d["source_house"], "target_house": d["target_house"],
                "window_index": w, "window_start": _window_timestamp(d["timestamp"], start),
                "actual_concurrent_on_majority": "3+" if majority >= 3 else str(majority),
                "actual_concurrent_on_max": "3+" if max_conc >= 3 else str(max_conc),
                "device": str(label), "category": category,
                "true_on_samples": int(a_on.sum()), "predicted_on_samples": int(p_on.sum()),
                "true_kwh": true_kwh, "predicted_kwh": pred_kwh,
                "signed_error_kwh": delta, "absolute_error_kwh": abs(delta),
                "aggregate_mean_w": float(d["aggregate_w"][start:stop].mean()),
                "aggregate_max_w": float(d["aggregate_w"][start:stop].max()),
            })
    cases.sort(key=lambda r: r["absolute_error_kwh"], reverse=True)
    for rank, case in enumerate(cases[:errors_limit], 1):
        case["rank"] = rank
    cases = cases[:errors_limit]
    return metrics, counts, cases


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("")
        return
    keys = list(dict.fromkeys(k for row in rows for k in row))
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--reference-dir", type=Path, default=BASELINE)
    p.add_argument("--candidate-dir", type=Path,
                   help="Optional competing NPZ directory; requires identical windows to reference")
    p.add_argument("--output-dir", type=Path, default=HERE)
    p.add_argument("--top-cases", type=int, default=200)
    a = p.parse_args()
    if a.top_cases < 0:
        p.error("--top-cases must be non-negative")
    a.output_dir.mkdir(parents=True, exist_ok=True)
    metric_rows, count_rows, case_rows = [], [], []
    files = sorted(a.reference_dir.glob("source*_target*.npz"))
    if not files:
        p.error(f"no source*_target*.npz files in {a.reference_dir}")
    for ref_path in files:
        ref = _read(ref_path)
        metric, counts, cases = analyze_one(ref, "reference", a.top_cases)
        metric_rows.extend(metric); count_rows.extend(counts); case_rows.extend(cases)
        if a.candidate_dir:
            cand_path = a.candidate_dir / ref_path.name
            if not cand_path.exists():
                raise FileNotFoundError(cand_path)
            cand = _read(cand_path)
            _assert_aligned(ref, cand, ref_path, cand_path)
            metric, counts, cases = analyze_one(cand, "candidate", a.top_cases)
            metric_rows.extend(metric); count_rows.extend(counts); case_rows.extend(cases)
    write_csv(a.output_dir / "stratum_metrics.csv", metric_rows)
    write_csv(a.output_dir / "stratum_counts.csv", count_rows)
    write_csv(a.output_dir / "high_error_cases.csv", case_rows)
    summary = {
        "command": "uv run python dataset/research_v1/concurrent/analyze.py " +
                   f"--reference-dir {a.reference_dir}" +
                   (f" --candidate-dir {a.candidate_dir}" if a.candidate_dir else ""),
        "reference_dir": str(a.reference_dir), "candidate_dir": str(a.candidate_dir) if a.candidate_dir else None,
        "outputs": ["stratum_counts.csv", "stratum_metrics.csv", "high_error_cases.csv"],
        "concurrency_definition": "At each 15-second row, count comparable labeled channels with y_true_w >= threshold; thresholds W: " + json.dumps(ON_W, sort_keys=True),
        "strata": ["0", "1", "2", "3+"],
        "f1_prediction_on": "p_on >= frozen source-house event threshold; event threshold comes from NPZ when present, else embedded baseline House 2/5 thresholds, else 0.5; if p_on is absent, use predicted watts >= actual ON threshold.",
        "high_error_case_definition": f"Top {a.top_cases} window/device pairs per model and source-target file, ranked by absolute kWh error; category uses actual ON watt thresholds and frozen event threshold.",
        "files": [x.name for x in files],
        "summary_counts": count_rows,
        "macro_by_model_and_concurrency": _macro_by_stratum(metric_rows),
    }
    (a.output_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")


def _macro_by_stratum(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for model in sorted(set(r["model"] for r in rows)):
        for value in ("0", "1", "2", "3+"):
            rr = [r for r in rows if r["model"] == model and r["stratum_value"] == value]
            f1s = [r["f1_on_off"] for r in rr if r["f1_on_off"] is not None]
            apes = [r["absolute_percentage_error"] for r in rr if r["absolute_percentage_error"] is not None]
            out.append({"model": model, "actual_concurrent_on": value,
                        "group_count": len(rr), "macro_f1_on_off": float(np.mean(f1s)) if f1s else None,
                        "macro_absolute_percentage_error": float(np.mean(apes)) if apes else None})
    return out


if __name__ == "__main__":
    main()
