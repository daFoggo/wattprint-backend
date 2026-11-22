"""Paired cross-house comparisons on the frozen 128-window target selections."""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from dataset.research_v1.evaluation.evaluate import DEFAULT_ON_W, evaluate, load_inputs  # noqa: E402

HERE = Path(__file__).resolve().parent
BASE = ROOT / "dataset/research_v1/baseline"
VERSIONS = {"v2.0": HERE / "predictions", "v2.1": HERE / "v2_1/predictions"}


def read_npz(path: Path) -> dict[str, np.ndarray]:
    with np.load(path, allow_pickle=False) as z:
        return {k: z[k] for k in z.files}


def f1(actual: np.ndarray, pred: np.ndarray) -> float | None:
    tp, fp, fn = int((actual & pred).sum()), int((~actual & pred).sum()), int((actual & ~pred).sum())
    return 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None


def metric_on_indices(z: dict, indices: np.ndarray, c: int):
    labels = z["labels"].astype(str).tolist()
    y = z["y_true_w"].reshape(-1, 256, len(labels))[indices, :, c].reshape(-1)
    p = z["y_pred_w"].reshape(-1, 256, len(labels))[indices, :, c].reshape(-1)
    prob = z["p_on"].reshape(-1, 256, len(labels))[indices, :, c].reshape(-1)
    on = y >= DEFAULT_ON_W[labels[c]]
    f1_value = f1(on, prob >= float(z["event_thresholds"][c]))
    signed = (p.sum() - y.sum()) * 15 / 3.6e6
    return f1_value, abs(float(signed))


def paired_ci(reference: dict, candidate: dict, reps: int = 200, seed: int = 17):
    labels = candidate["labels"].astype(str).tolist()
    n = len(candidate["selected_window_indices"])
    rng = np.random.default_rng(seed)
    delta_f1, delta_abs = [], []
    for _ in range(reps):
        indices = rng.integers(0, n, size=n)
        pair_f1, pair_abs = [], []
        for c in range(len(labels)):
            b_f1, b_abs = metric_on_indices(reference, indices, c)
            v_f1, v_abs = metric_on_indices(candidate, indices, c)
            if b_f1 is not None and v_f1 is not None:
                pair_f1.append(v_f1 - b_f1)
            pair_abs.append(v_abs - b_abs)
        if pair_f1:
            delta_f1.append(float(np.mean(pair_f1)))
        delta_abs.append(float(np.mean(pair_abs)))
    return {"replicates": reps, "seed": seed, "resample_unit": "paired 256-step window",
            "delta_macro_f1_ci95": np.percentile(delta_f1, [2.5, 97.5]).tolist() if delta_f1 else [None, None],
            "delta_mean_absolute_kwh_ci95": np.percentile(delta_abs, [2.5, 97.5]).tolist()}


def write_csv(path: Path, rows: list[dict]):
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader(), writer.writerows(rows)


def main():
    rows, strata_rows, summaries = [], [], []
    for target in (2, 3, 5, 6):
        for version, directory in VERSIONS.items():
            candidate_path = directory / f"loho_target{target}.npz"
            if not candidate_path.exists():
                raise FileNotFoundError(candidate_path)
            candidate = read_npz(candidate_path)
            c_data = load_inputs([candidate_path])
            c_metrics, c_strata, _ = evaluate(c_data, DEFAULT_ON_W, 50.0, None)
            for source in (2, 5):
                if source == target:
                    continue  # source bundle trained on target: in-house, invalid reference here
                base_path = BASE / f"source{source}_target{target}.npz"
                reference = read_npz(base_path)
                if not all(np.array_equal(reference[k], candidate[k]) for k in
                           ("labels", "timestamp", "aggregate_w", "y_true_w", "selected_window_indices")):
                    raise ValueError(f"unpaired target {target}, source {source}, {version}")
                b_data = load_inputs([base_path])
                b_metrics, b_strata, _ = evaluate(b_data, DEFAULT_ON_W, 50.0, None)
                for b, c in zip(b_metrics, c_metrics, strict=True):
                    rows.append({"version": version, "target_house": target, "baseline_source_house": source,
                                 "device": b["device"], "samples": b["samples"], "true_on_events": b["true_on_events"],
                                 "true_kwh": b["true_kwh"], "baseline_pred_kwh": b["predicted_kwh"],
                                 "candidate_pred_kwh": c["predicted_kwh"],
                                 "baseline_signed_error_kwh": b["signed_error_kwh"],
                                 "candidate_signed_error_kwh": c["signed_error_kwh"],
                                 "baseline_absolute_error_kwh": b["absolute_error_kwh"],
                                 "candidate_absolute_error_kwh": c["absolute_error_kwh"],
                                 "baseline_f1": b["f1_on_off"], "candidate_f1": c["f1_on_off"],
                                 "delta_f1": c["f1_on_off"] - b["f1_on_off"] if
                                 b["f1_on_off"] is not None and c["f1_on_off"] is not None else None})
                for b, c in zip(b_strata, c_strata, strict=True):
                    if (b["stratum"], b["stratum_value"], b["device"]) != (c["stratum"], c["stratum_value"], c["device"]):
                        raise ValueError("strata did not align")
                    strata_rows.append({"version": version, "target_house": target, "baseline_source_house": source,
                                        "stratum": b["stratum"], "stratum_value": b["stratum_value"],
                                        "device": b["device"], "samples": b["samples"],
                                        "baseline_f1": b["f1_on_off"], "candidate_f1": c["f1_on_off"],
                                        "baseline_abs_kwh": b["absolute_error_kwh"],
                                        "candidate_abs_kwh": c["absolute_error_kwh"]})
                pair = [r for r in rows if r["version"] == version and r["target_house"] == target and r["baseline_source_house"] == source]
                summaries.append({"version": version, "target_house": target, "baseline_source_house": source,
                                  "baseline_macro_f1": float(np.mean([r["baseline_f1"] for r in pair if r["baseline_f1"] is not None])),
                                  "candidate_macro_f1": float(np.mean([r["candidate_f1"] for r in pair if r["candidate_f1"] is not None])),
                                  "baseline_mean_abs_kwh": float(np.mean([r["baseline_absolute_error_kwh"] for r in pair])),
                                  "candidate_mean_abs_kwh": float(np.mean([r["candidate_absolute_error_kwh"] for r in pair])),
                                  "paired_bootstrap": paired_ci(reference, candidate)})
    write_csv(HERE / "paired_metrics.csv", rows)
    write_csv(HERE / "paired_strata.csv", strata_rows)
    (HERE / "comparison.json").write_text(json.dumps({"comparisons": summaries,
        "note": "v2.0 versus v2.1 is a multi-change exploratory comparison; production source bundles have less training-house coverage than LOHO TCN models. No target was used for training or model selection."}, indent=2) + "\n")
    for r in summaries:
        print(f"{r['version']} target {r['target_house']} baseline {r['baseline_source_house']}: "
              f"F1 {r['baseline_macro_f1']:.3f}->{r['candidate_macro_f1']:.3f}, "
              f"abs kWh {r['baseline_mean_abs_kwh']:.3f}->{r['candidate_mean_abs_kwh']:.3f}")


if __name__ == "__main__":
    main()
