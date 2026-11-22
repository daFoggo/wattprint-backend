#!/usr/bin/env python3
"""Evaluate NILM prediction NPZ files and write reproducible CSV/JSON summaries.

Expected arrays are row-aligned: house_id, timestamp, aggregate_w, y_true_w,
y_pred_w, labels, sample_seconds. y_true_w and y_pred_w have shape (N, C).
Optional p_on has shape (N, C), and event_thresholds has shape (C,). The CLI
accepts arrays with a single house scalar or one house ID per row.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

REQUIRED = {"house_id", "timestamp", "aggregate_w", "y_true_w", "y_pred_w", "labels", "sample_seconds"}
DEFAULT_ON_W = {
    "Fridge": 50.0, "Freezer": 50.0, "WashMach": 20.0, "Dishwash": 10.0,
    "Microwave": 200.0, "Toaster": 200.0, "Kettle": 1000.0,
}
POWER_BINS = (0.0, 100.0, 500.0, 1500.0, math.inf)
POWER_NAMES = ("0-100W", "100-500W", "500-1500W", "1500W+", "unknown")


def _scalar(z: Any, name: str) -> Any:
    value = np.asarray(z[name])
    if value.size != 1:
        raise ValueError(f"{name} must contain exactly one value")
    return value.reshape(()).item()


def _timestamp_seconds(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values)
    if np.issubdtype(values.dtype, np.datetime64):
        return values.astype("datetime64[ns]").astype(np.int64) / 1e9
    if values.dtype.kind in "iuf":
        return values.astype(np.float64)
    parsed = values.astype("datetime64[ns]")
    if np.any(np.isnat(parsed)):
        raise ValueError("timestamp contains invalid datetime values")
    return parsed.astype(np.int64) / 1e9


def load_inputs(paths: list[Path]) -> dict[str, Any]:
    parts: dict[str, list[np.ndarray]] = {k: [] for k in ("house_id", "timestamp", "aggregate_w", "y_true_w", "y_pred_w", "p_on")}
    labels: np.ndarray | None = None
    dt: float | None = None
    thresholds: np.ndarray | None = None
    any_probability = False
    p_on_presence: bool | None = None
    threshold_presence: bool | None = None
    for path in paths:
        with np.load(path, allow_pickle=False) as z:
            missing = REQUIRED.difference(z.files)
            if missing:
                raise ValueError(f"{path}: missing required arrays: {', '.join(sorted(missing))}")
            current_labels = np.asarray(z["labels"]).astype(str).reshape(-1)
            if not len(current_labels) or len(set(current_labels.tolist())) != len(current_labels):
                raise ValueError(f"{path}: labels must be nonempty and unique")
            current_dt = float(_scalar(z, "sample_seconds"))
            if not np.isfinite(current_dt) or current_dt <= 0:
                raise ValueError(f"{path}: sample_seconds must be positive and finite")
            y = np.asarray(z["y_true_w"], dtype=np.float64)
            p = np.asarray(z["y_pred_w"], dtype=np.float64)
            n, c = y.shape if y.ndim == 2 else (-1, -1)
            if n < 1 or c != len(current_labels) or p.shape != y.shape:
                raise ValueError(f"{path}: y_true_w and y_pred_w must have shape (N, len(labels))")
            h = np.asarray(z["house_id"])
            if h.size == 1:
                h = np.repeat(h.reshape(-1), n)
            else:
                h = h.reshape(-1)
            a = np.asarray(z["aggregate_w"], dtype=np.float64).reshape(-1)
            ts = _timestamp_seconds(z["timestamp"]).reshape(-1)
            if len(h) != n or len(a) != n or len(ts) != n:
                raise ValueError(f"{path}: row arrays must all have N={n} values")
            if not (np.isfinite(y).all() and np.isfinite(p).all() and np.isfinite(a).all() and np.isfinite(ts).all()):
                raise ValueError(f"{path}: power and timestamp arrays must be finite")
            if labels is None:
                labels, dt = current_labels, current_dt
            elif not np.array_equal(labels, current_labels) or not np.isclose(dt, current_dt):
                raise ValueError(f"{path}: labels/sample_seconds differ from the first input")
            current_has_probability = "p_on" in z.files
            if p_on_presence is None:
                p_on_presence = current_has_probability
            elif p_on_presence != current_has_probability:
                raise ValueError("p_on must be present in all input files or none")
            prob = np.asarray(z["p_on"], dtype=np.float64) if current_has_probability else np.full_like(y, np.nan)
            if prob.shape != y.shape or (current_has_probability and
                                          (not np.isfinite(prob).all() or (prob < 0).any() or (prob > 1).any())):
                raise ValueError(f"{path}: p_on must be probabilities with shape matching y_true_w")
            if current_has_probability:
                any_probability = True
            parts["house_id"].append(h.astype(str))
            parts["timestamp"].append(ts)
            parts["aggregate_w"].append(a)
            parts["y_true_w"].append(y)
            parts["y_pred_w"].append(p)
            parts["p_on"].append(prob)
            current_has_thresholds = "event_thresholds" in z.files
            if threshold_presence is None:
                threshold_presence = current_has_thresholds
            elif threshold_presence != current_has_thresholds:
                raise ValueError("event_thresholds must be present in all input files or none")
            if current_has_thresholds:
                th = np.asarray(z["event_thresholds"], dtype=np.float64).reshape(-1)
                if th.size == 1:
                    th = np.repeat(th, c)
                if th.shape != (c,) or not np.isfinite(th).all() or ((th < 0) | (th > 1)).any():
                    raise ValueError(f"{path}: event_thresholds must be probabilities, scalar or one per label")
                if thresholds is None:
                    thresholds = th
                elif not np.allclose(thresholds, th):
                    raise ValueError(f"{path}: event_thresholds differ between inputs")
    assert labels is not None and dt is not None
    return {k: np.concatenate(v, axis=0) for k, v in parts.items()} | {
        "labels": labels, "sample_seconds": dt, "event_thresholds": thresholds,
        "has_p_on": any_probability,
    }


def f1_score(actual: np.ndarray, predicted: np.ndarray) -> float | None:
    tp = int(np.count_nonzero(actual & predicted))
    fp = int(np.count_nonzero(~actual & predicted))
    fn = int(np.count_nonzero(actual & ~predicted))
    return 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None


def _events(on: np.ndarray, timestamps: np.ndarray, sample_seconds: float) -> int:
    if not len(on):
        return 0
    ordered = np.argsort(timestamps, kind="stable")
    active = on[ordered]
    times = timestamps[ordered]
    new_segment = np.r_[True, np.diff(times) > sample_seconds * 1.5]
    return int(np.count_nonzero(active & (~np.r_[False, active[:-1]] | new_segment)))


def _safe_div(n: float, d: float) -> float | None:
    return n / d if d > 1e-12 else None


def _summary(indices: np.ndarray, data: dict[str, Any], c: int, on_threshold: float,
             probability_threshold: float | None) -> dict[str, Any]:
    dt = data["sample_seconds"]
    truth = data["y_true_w"][indices, c]
    pred = data["y_pred_w"][indices, c]
    t_kwh = float(truth.sum() * dt / 3_600_000)
    p_kwh = float(pred.sum() * dt / 3_600_000)
    actual_on = truth >= on_threshold
    predicted_on = (data["p_on"][indices, c] >= probability_threshold
                    if probability_threshold is not None and data["has_p_on"]
                    else pred >= on_threshold)
    f1 = f1_score(actual_on, predicted_on)
    return {
        "samples": int(len(indices)), "on_samples": int(actual_on.sum()),
        "true_on_events": _events(actual_on, data["timestamp"][indices], dt),
        "predicted_on_events": _events(predicted_on, data["timestamp"][indices], dt),
        "true_kwh": t_kwh, "predicted_kwh": p_kwh,
        "signed_error_kwh": p_kwh - t_kwh, "absolute_error_kwh": abs(p_kwh - t_kwh),
        "absolute_percentage_error": 100 * abs(p_kwh - t_kwh) / t_kwh if t_kwh > 1e-12 else None,
        "f1_on_off": f1,
    }


def evaluate(data: dict[str, Any], on_thresholds: dict[str, float], default_on_w: float,
             override_event_threshold: float | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    labels = data["labels"]
    thresholds = data["event_thresholds"]
    if override_event_threshold is not None:
        thresholds = np.repeat(override_event_threshold, len(labels))
    if thresholds is None and data["has_p_on"]:
        thresholds = np.repeat(0.5, len(labels))
    row_metrics: list[dict[str, Any]] = []
    groups: list[tuple[str, str, np.ndarray]] = []
    houses = data["house_id"]
    for house in sorted(set(houses.tolist())):
        hi = np.flatnonzero(houses == house)
        for c, label in enumerate(labels):
            threshold = on_thresholds.get(label, default_on_w)
            metric = _summary(hi, data, c, threshold,
                              None if thresholds is None else float(thresholds[c]))
            row_metrics.append({"house_id": house, "device": label, "on_threshold_w": threshold,
                                "event_threshold": None if thresholds is None else float(thresholds[c]), **metric})
            groups.append((house, str(label), hi))

    strata_rows: list[dict[str, Any]] = []
    for house in sorted(set(houses.tolist())):
        hi = np.flatnonzero(houses == house)
        concurrent = np.zeros(len(hi), dtype=int)
        for c, label in enumerate(labels):
            concurrent += data["y_true_w"][hi, c] >= on_thresholds.get(str(label), default_on_w)
        aggregate = data["aggregate_w"][hi]
        for stratum_name, name, mask in (
            *(("aggregate_power", POWER_NAMES[i], (aggregate >= POWER_BINS[i]) & (aggregate < POWER_BINS[i + 1])) for i in range(4)),
            *(("concurrent_actual_on", name, concurrent == k) for k, name in enumerate(("0", "1", "2"))),
            ("concurrent_actual_on", "3+", concurrent >= 3),
        ):
            si = hi[mask]
            for c, label in enumerate(labels):
                metric = _summary(si, data, c, on_thresholds.get(str(label), default_on_w),
                                  None if thresholds is None else float(thresholds[c]))
                strata_rows.append({"house_id": house, "stratum": stratum_name, "stratum_value": name,
                                    "device": str(label), **metric})

    def macro(rows: list[dict[str, Any]]) -> dict[str, Any]:
        usable_f1 = [r["f1_on_off"] for r in rows if r["f1_on_off"] is not None]
        usable_ape = [r["absolute_percentage_error"] for r in rows if r["absolute_percentage_error"] is not None]
        return {"house_device_groups": len(rows), "macro_f1_on_off": float(np.mean(usable_f1)) if usable_f1 else None,
                "macro_absolute_percentage_error": float(np.mean(usable_ape)) if usable_ape else None}

    return row_metrics, strata_rows, macro(row_metrics)


def block_bootstrap(data: dict[str, Any], on_thresholds: dict[str, float], default_on_w: float,
                    event_threshold: float | None, iterations: int, block_seconds: float,
                    seed: int) -> dict[str, Any]:
    if iterations <= 0:
        return {"iterations": 0, "block_seconds": block_seconds, "seed": seed}
    rng = np.random.default_rng(seed)
    samples_f1: list[float] = []
    samples_ape: list[float] = []
    houses = data["house_id"]
    dt = data["sample_seconds"]
    for _ in range(iterations):
        chosen: dict[str, list[np.ndarray]] = {}
        for house in sorted(set(houses.tolist())):
            hi = np.flatnonzero(houses == house)
            order = hi[np.argsort(data["timestamp"][hi], kind="stable")]
            block_n = max(1, int(round(block_seconds / dt)))
            # Keep temporal gaps as separate resampling domains.
            gaps = np.flatnonzero(np.diff(data["timestamp"][order]) > 1.5 * dt) + 1
            segments = np.split(order, gaps)
            blocks = [segment[i:i + block_n] for segment in segments for i in range(0, len(segment), block_n)]
            if blocks:
                picked = rng.integers(0, len(blocks), size=len(blocks))
                chosen[house] = [blocks[i] for i in picked]
        if not chosen:
            continue
        values_f1, values_ape = [], []
        thresholds = data["event_thresholds"]
        if event_threshold is not None:
            thresholds = np.repeat(event_threshold, len(data["labels"]))
        elif thresholds is None and data["has_p_on"]:
            thresholds = np.repeat(0.5, len(data["labels"]))
        for house in sorted(chosen):
            # Merge sampled blocks back into a house replicate before computing
            # F1/energy; averaging block-level scores would change the estimand.
            idx = np.concatenate(chosen[house])
            for c, label in enumerate(data["labels"]):
                threshold_w = on_thresholds.get(str(label), default_on_w)
                truth = data["y_true_w"][idx, c]
                pred = data["y_pred_w"][idx, c]
                actual_on = truth >= threshold_w
                predicted_on = (data["p_on"][idx, c] >= thresholds[c]
                                if data["has_p_on"] and thresholds is not None
                                else pred >= threshold_w)
                score = f1_score(actual_on, predicted_on)
                if score is not None:
                    values_f1.append(score)
                true_kwh = float(truth.sum() * dt / 3_600_000)
                pred_kwh = float(pred.sum() * dt / 3_600_000)
                if true_kwh > 1e-12:
                    values_ape.append(100 * abs(pred_kwh - true_kwh) / true_kwh)
        if values_f1:
            samples_f1.append(float(np.mean(values_f1)))
        if values_ape:
            samples_ape.append(float(np.mean(values_ape)))

    def interval(values: list[float]) -> dict[str, float | None]:
        if not values:
            return {"low_95": None, "high_95": None}
        low, high = np.percentile(values, [2.5, 97.5])
        return {"low_95": float(low), "high_95": float(high)}
    return {"iterations": iterations, "block_seconds": block_seconds, "seed": seed,
            "macro_f1_on_off_ci95": interval(samples_f1),
            "macro_absolute_percentage_error_ci95": interval(samples_ape),
            "note": "Percentile intervals resample contiguous fixed-duration blocks within each house; device macro metrics are computed per replicate."}


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("\n", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def parse_thresholds(items: list[str]) -> dict[str, float]:
    out: dict[str, float] = {}
    for item in items:
        if "=" not in item:
            raise argparse.ArgumentTypeError(f"expected LABEL=WATTS, got {item!r}")
        label, value = item.rsplit("=", 1)
        try:
            number = float(value)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(f"invalid threshold in {item!r}") from exc
        if not label or not math.isfinite(number) or number < 0:
            raise argparse.ArgumentTypeError(f"threshold must be finite and nonnegative: {item!r}")
        out[label] = number
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", type=Path, help="Prediction NPZ file(s) with matching labels and sample period")
    parser.add_argument("--out-dir", type=Path, default=Path("evaluation-results"))
    parser.add_argument("--prefix", default="", help="Prefix for the three output filenames")
    parser.add_argument("--on-threshold", action="append", default=[], metavar="LABEL=WATTS",
                        help="Override actual ON threshold; repeat for multiple labels")
    parser.add_argument("--default-on-threshold-w", type=float, default=50.0,
                        help="Actual ON threshold used for labels without a known/overridden threshold (default: 50)")
    parser.add_argument("--event-threshold", type=float,
                        help="Override p_on event decision threshold; defaults to NPZ thresholds, then 0.5")
    parser.add_argument("--bootstrap-iterations", type=int, default=1000,
                        help="Block bootstrap replicates; set 0 to disable (default: 1000)")
    parser.add_argument("--block-seconds", type=float, default=3600,
                        help="Contiguous block duration for bootstrap (default: 3600)")
    parser.add_argument("--seed", type=int, default=17)
    args = parser.parse_args()
    if args.default_on_threshold_w < 0 or not math.isfinite(args.default_on_threshold_w):
        parser.error("--default-on-threshold-w must be finite and nonnegative")
    if args.event_threshold is not None and not 0 <= args.event_threshold <= 1:
        parser.error("--event-threshold must be between 0 and 1")
    if args.bootstrap_iterations < 0 or args.block_seconds <= 0:
        parser.error("bootstrap iterations must be nonnegative and block-seconds positive")
    try:
        overrides = parse_thresholds(args.on_threshold)
        data = load_inputs(args.inputs)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    actual_thresholds = DEFAULT_ON_W | overrides
    metrics, strata, macro = evaluate(data, actual_thresholds, args.default_on_threshold_w, args.event_threshold)
    bootstrap = block_bootstrap(data, actual_thresholds, args.default_on_threshold_w,
                                args.event_threshold, args.bootstrap_iterations, args.block_seconds, args.seed)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    prefix = args.prefix
    write_csv(args.out_dir / f"{prefix}house_device_metrics.csv", metrics)
    write_csv(args.out_dir / f"{prefix}stratified_metrics.csv", strata)
    report = {
        "evaluation_version": "1.0.0", "inputs": [str(p.resolve()) for p in args.inputs],
        "labels": data["labels"].tolist(), "houses": sorted(set(data["house_id"].tolist())),
        "samples": int(len(data["house_id"])), "sample_seconds": data["sample_seconds"],
        "on_threshold_w": {str(label): actual_thresholds.get(str(label), args.default_on_threshold_w) for label in data["labels"]},
        "event_thresholds": None if not data["has_p_on"] else (np.repeat(args.event_threshold, len(data["labels"])) if args.event_threshold is not None else (data["event_thresholds"] if data["event_thresholds"] is not None else np.repeat(0.5, len(data["labels"])))).tolist(),
        "macro": macro, "block_bootstrap": bootstrap,
        "aggregate_power_bins_w": [0, 100, 500, 1500, None],
    }
    (args.out_dir / f"{prefix}summary.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"out_dir": str(args.out_dir.resolve()), "macro": macro,
                      "bootstrap": bootstrap}, indent=2))


if __name__ == "__main__":
    main()
