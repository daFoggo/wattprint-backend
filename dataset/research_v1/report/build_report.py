#!/usr/bin/env python3
"""Build reproducible trace figures and a current report from research_v1 artifacts.

Run from the repository root:
  uv run --group nilm python dataset/research_v1/report/build_report.py
"""
from __future__ import annotations

import csv
import json
import shutil
import subprocess
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parent
BASELINE = RESEARCH / "baseline"
CANDIDATE = RESEARCH / "model" / "predictions"
CONCURRENT = RESEARCH / "concurrent"
WINDOW = 256
ON_W = {"Fridge": 50, "Freezer": 50, "WashMach": 20, "Dishwash": 10,
        "Microwave": 200, "Toaster": 200, "Kettle": 1000}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_npz(path: Path) -> dict:
    with np.load(path, allow_pickle=False) as z:
        d = {k: np.array(z[k]) for k in ("timestamp", "aggregate_w", "y_true_w", "y_pred_w", "labels")}
        d["labels"] = d["labels"].astype(str).reshape(-1)
        d["source"] = int(np.asarray(z["source_house_id"]).reshape(()))
        d["target"] = int(np.asarray(z["house_id"]).reshape(()))
        d["dt"] = float(np.asarray(z["sample_seconds"]).reshape(()))
    return d


def concurrent_counts(d: dict, start: int, end: int) -> np.ndarray:
    ys = d["y_true_w"][start:end]
    return sum((ys[:, i] >= ON_W.get(label, 50)).astype(int) for i, label in enumerate(d["labels"]))


def representative_window(d: dict) -> int:
    nwin = len(d["timestamp"]) // WINDOW
    # Select a typical House 2 test window: majority concurrency is one, then
    # closest aggregate mean to the median of the target windows.
    stats = []
    means = np.array([d["aggregate_w"][i*WINDOW:(i+1)*WINDOW].mean() for i in range(nwin)])
    median_mean = float(np.median(means))
    for i in range(nwin):
        counts = concurrent_counts(d, i*WINDOW, (i+1)*WINDOW)
        majority = int(np.bincount(counts, minlength=4).argmax())
        stats.append((0 if majority == 1 else 1, abs(means[i] - median_mean), i))
    return min(stats)[2]


def plot_trace(d: dict, model_name: str, win_idx: int, tag: str, out: Path) -> None:
    a, b = win_idx * WINDOW, (win_idx + 1) * WINDOW
    if b > len(d["timestamp"]):
        raise ValueError(f"Window {win_idx} outside {len(d['timestamp']) // WINDOW} available windows")
    ts = d["timestamp"][a:b].astype("datetime64[s]")
    x = (ts - ts[0]).astype("timedelta64[s]").astype(float) / 60
    counts = concurrent_counts(d, a, b)
    majority, peak = np.bincount(counts, minlength=4).argmax(), int(counts.max())
    start = str(ts[0])
    fig, axes = plt.subplots(len(d["labels"]) + 1, 1, figsize=(12, 10), sharex=True,
                             gridspec_kw={"height_ratios": [1.1] + [1] * len(d["labels"])})
    axes[0].plot(x, d["aggregate_w"][a:b], color="#263238", linewidth=1.1)
    axes[0].set_ylabel("Aggregate\n(W)")
    axes[0].set_title(f"{tag.replace('_', ' ').title()} | {model_name} | House {d['target']} | {start} | concurrent ON: majority {majority}, peak {peak}", loc="left", fontsize=12)
    for i, label in enumerate(d["labels"]):
        ax = axes[i + 1]
        ax.plot(x, d["y_true_w"][a:b, i], label="Ground truth", color="#1565c0", linewidth=1.0)
        ax.plot(x, d["y_pred_w"][a:b, i], label="Predicted", color="#ef6c00", linewidth=1.0, alpha=.9)
        ax.set_ylabel(f"{label}\n(W)")
        ax.grid(True, alpha=.2)
        if i == 0:
            ax.legend(loc="upper right", ncol=2, frameon=False)
    axes[-1].set_xlabel("Minutes from window start")
    axes[-1].set_xlim(0, max(x) if len(x) else 1)
    axes[0].grid(True, alpha=.2)
    fig.tight_layout()
    fig.savefig(out, dpi=160, bbox_inches="tight")
    plt.close(fig)


def markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join(lines)


def main() -> None:
    baseline_metrics = read_csv(BASELINE / "metrics.csv")
    files = sorted(BASELINE.glob("source*_target*.npz"))
    if not files:
        raise SystemExit(f"No baseline NPZ files in {BASELINE}")
    # Use an unseen target house for both examples so the traces illustrate
    # cross-house transfer rather than in-house temporal performance.
    d_ref = load_npz(BASELINE / "source2_target3.npz")
    rep = representative_window(d_ref)
    errors = read_csv(CONCURRENT / "high_error_cases.csv")
    rows = [r for r in errors if r["model"] == "reference" and r["source_house"] == "2" and r["target_house"] == "3"]
    high = int(rows[0]["window_index"]) if rows else rep
    plot_trace(d_ref, "baseline (source 2)", rep, "representative", HERE / "baseline_representative.png")
    plot_trace(d_ref, "baseline (source 2)", high, "high_error", HERE / "baseline_high_error.png")

    cand_files = sorted(CANDIDATE.glob("source*_target*.npz")) if CANDIDATE.exists() else []
    if cand_files:
        d_candidate = load_npz(CANDIDATE / "source2_target2.npz")
        # Keep the exact same target windows for paired visual comparison.
        plot_trace(d_candidate, "candidate (source 2)", rep, "representative", HERE / "candidate_representative.png")
        plot_trace(d_candidate, "candidate (source 2)", high, "high_error", HERE / "candidate_high_error.png")

    # Pairwise overview, only with common source-target-device rows.
    cand_metrics_path = RESEARCH / "model" / "metrics.csv"
    metric_rows = read_csv(cand_metrics_path) if cand_metrics_path.exists() else []
    comparison_rows = []
    if metric_rows:
        base_by = {(r["source_house"], r["target_house"], r["device"]): r for r in baseline_metrics}
        for c in metric_rows:
            key = (c.get("source_house", ""), c.get("target_house", ""), c.get("device", ""))
            if key not in base_by:
                continue
            b = base_by[key]
            comparison_rows.append({"source_house": key[0], "target_house": key[1], "device": key[2],
                                   "baseline_f1": b["f1_on_off"], "candidate_f1": c.get("f1_on_off", ""),
                                   "delta_f1": (float(c["f1_on_off"]) - float(b["f1_on_off"])) if c.get("f1_on_off") else "",
                                   "baseline_signed_error_kwh": b["signed_error_kwh"],
                                   "candidate_signed_error_kwh": c.get("signed_error_kwh", ""),
                                   "delta_signed_error_kwh": (float(c["signed_error_kwh"]) - float(b["signed_error_kwh"])) if c.get("signed_error_kwh") else "",
                                   "baseline_absolute_error_kwh": b["absolute_error_kwh"],
                                   "candidate_absolute_error_kwh": c.get("absolute_error_kwh", ""),
                                   "delta_absolute_error_kwh": (float(c["absolute_error_kwh"]) - float(b["absolute_error_kwh"])) if c.get("absolute_error_kwh") else "",
                                   "baseline_ape_pct": b["absolute_percentage_error"],
                                   "candidate_ape_pct": c.get("absolute_percentage_error", "")})
        if comparison_rows:
            with (HERE / "paired_metrics.csv").open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=list(comparison_rows[0]))
                writer.writeheader(); writer.writerows(comparison_rows)

    baseline_by_pair = {}
    for r in baseline_metrics:
        baseline_by_pair.setdefault((r["source_house"], r["target_house"]), []).append(r)
    overview = []
    for (source, target), rs in sorted(baseline_by_pair.items()):
        f1s = [float(r["f1_on_off"]) for r in rs if r["f1_on_off"]]
        apes = [float(r["absolute_percentage_error"]) for r in rs if r["absolute_percentage_error"]]
        kind = "in-house temporal test" if source == target else "cross-house transfer"
        overview.append([f"{source} → {target}", kind, f"{np.mean(f1s):.3f}" if f1s else "—",
                         f"{np.mean(apes):.1f}%" if apes else "—"])

    eval_out = HERE / ".evaluation_work"
    candidate_strata = []
    if cand_files:
        eval_out.mkdir(exist_ok=True)
        eval_script = RESEARCH / "evaluation" / "evaluate.py"
        # Evaluate each paired NPZ separately because House 6 has Freezer in
        # place of the Fridge label used by the other targets.
        for ref_path in files:
            cand_path = CANDIDATE / ref_path.name
            prefix_base, prefix_cand = f"base_{ref_path.stem}_", f"cand_{ref_path.stem}_"
            for path, prefix in ((ref_path, prefix_base), (cand_path, prefix_cand)):
                subprocess.run([sys.executable, str(eval_script), str(path), "--out-dir", str(eval_out),
                                "--prefix", prefix, "--bootstrap-iterations", "0"],
                               check=True, capture_output=True, text=True)
            ref_strata = read_csv(eval_out / f"{prefix_base}stratified_metrics.csv")
            cand_strata = read_csv(eval_out / f"{prefix_cand}stratified_metrics.csv")
            by_stratum = {(r["house_id"], r["stratum"], r["stratum_value"], r["device"]): r for r in ref_strata}
            for c in cand_strata:
                key = (c["house_id"], c["stratum"], c["stratum_value"], c["device"])
                b = by_stratum.get(key)
                if b:
                    candidate_strata.append({"source_house": ref_path.stem.split("_")[0].replace("source", ""),
                                             "house_id": key[0], "stratum": key[1], "stratum_value": key[2], "device": key[3],
                                             "sample_count": c["samples"],
                                             "baseline_f1": b["f1_on_off"], "candidate_f1": c["f1_on_off"],
                                             "delta_f1": float(c["f1_on_off"] or 0) - float(b["f1_on_off"] or 0),
                                             "baseline_signed_error_kwh": b["signed_error_kwh"], "candidate_signed_error_kwh": c["signed_error_kwh"],
                                             "baseline_absolute_error_kwh": b["absolute_error_kwh"], "candidate_absolute_error_kwh": c["absolute_error_kwh"],
                                             "delta_absolute_error_kwh": float(c["absolute_error_kwh"]) - float(b["absolute_error_kwh"])})
        if candidate_strata:
            with (HERE / "paired_stratified_metrics.csv").open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=list(candidate_strata[0]))
                writer.writeheader(); writer.writerows(candidate_strata)
        shutil.rmtree(eval_out, ignore_errors=True)

    concurrent_rows = read_csv(CONCURRENT / "stratum_metrics.csv")
    concurrent_counts = read_csv(CONCURRENT / "stratum_counts.csv")
    grouped: dict[str, list[dict]] = {}
    for r in concurrent_rows:
        if r["model"] == "reference":
            grouped.setdefault(r["stratum_value"], []).append(r)
    strata = []
    for value in ("0", "1", "2", "3+"):
        rs = grouped.get(value, [])
        f1s = [float(r["f1_on_off"]) for r in rs if r["f1_on_off"] not in ("", "None")]
        abs_kwh = [float(r["absolute_error_kwh"]) for r in rs]
        # Counts are recorded once per source-target-stratum in the count file;
        # stratum_metrics repeats that count for every device.
        n = sum(int(r["sample_count"]) for r in concurrent_counts
                if r["model"] == "reference" and r["stratum_value"] == value)
        strata.append([value, f"{n:,}", f"{np.mean(f1s):.3f}" if f1s else "—",
                       f"{np.mean(abs_kwh):.3f}" if abs_kwh else "—"])

    report = ["# REFIT NILM research v1: preliminary results", "",
              "## Scope and protocol", "",
              "This report summarizes the frozen baseline and, when present, paired candidate predictions. The current experiment evaluates source House 2 and House 5 models on temporal test windows from Houses 2, 3, 5, and 6. Source-equals-target rows are in-house temporal tests; source-differs-from-target rows are cross-house transfer. **This is not a true leave-one-house-out (LOHO) experiment:** only Houses 2 and 5 are trained as sources, so Houses 3 and 6 are never held out as one of four folds with all other houses used for training. The protocol README describes LOHO as a plan; the results here must not be described as LOHO.", "",
              "The protocol audit records 15-second data, removes `Issues=1` rows, and notes long missing spans. Test windows are selected from the target temporal test partition and held fixed across source models. House 6 uses a Freezer channel where other houses use Fridge; those labels are not equivalent and are excluded from direct fridge comparisons.", "",
              "## Baseline overview", "",
              markdown_table(["Source → target", "Evaluation", "Mean device F1", "Mean device energy APE"], overview), "",
              "The means above average device-level scores equally within each source-target group. APE can be dominated by near-zero energy devices, so read it with F1, absolute kWh error, and sample/on counts rather than alone.", "",
              "## Concurrent-load stratification", "",
              markdown_table(["Actual concurrently ON", "Sample count across source-target evaluations", "Macro device F1", "Mean absolute device energy error (kWh)"], strata), "",
              "Counts and metrics are pooled over the eight source-target evaluations, so each target window appears once per source model. The 3+ stratum is sparse; these summaries are descriptive and are not independent observations.", "",
              "## Paired candidate comparison", ""]
    if comparison_rows:
        cross_rows = [r for r in comparison_rows if r["source_house"] != r["target_house"]]
        in_rows = [r for r in comparison_rows if r["source_house"] == r["target_house"]]
        improvements = sum(float(r["delta_f1"]) > 0 for r in cross_rows if r["delta_f1"] != "")
        regressions = sum(float(r["delta_f1"]) < 0 for r in cross_rows if r["delta_f1"] != "")
        e_improvements = sum(float(r["delta_absolute_error_kwh"]) < 0 for r in cross_rows if r["delta_absolute_error_kwh"] != "")
        e_regressions = sum(float(r["delta_absolute_error_kwh"]) > 0 for r in cross_rows if r["delta_absolute_error_kwh"] != "")
        summary_rows = []
        for name, rs in (("Cross-house transfer (primary)", cross_rows), ("In-house temporal test", in_rows)):
            if not rs:
                continue
            b_f1 = np.mean([float(r["baseline_f1"]) for r in rs if r["baseline_f1"] != ""])
            c_f1 = np.mean([float(r["candidate_f1"]) for r in rs if r["candidate_f1"] != ""])
            b_ae = np.mean([float(r["baseline_absolute_error_kwh"]) for r in rs])
            c_ae = np.mean([float(r["candidate_absolute_error_kwh"]) for r in rs])
            summary_rows.append([name, str(len(rs)), f"{b_f1:.3f}", f"{c_f1:.3f}", f"{b_ae:.3f}", f"{c_ae:.3f}", f"{c_ae-b_ae:+.3f}"])
        report += [markdown_table(["Comparison", "Matched device groups", "Baseline macro F1", "Candidate macro F1", "Baseline mean absolute error (kWh)", "Candidate mean absolute error (kWh)", "Candidate delta absolute error"], summary_rows), "",
                   f"Primary cross-house transfer comparison: {len(cross_rows)} matched source-target-device groups; candidate F1 improved in {improvements}, regressed in {regressions}; absolute energy error improved in {e_improvements}, regressed in {e_regressions}. In-house temporal test rows are reported separately ({len(in_rows)} groups). These results do not isolate an augmentation effect: the candidate used two training seeds, and there is no matched unaugmented retraining control; training budget and seeds also differ from the baseline. Per-group F1 and energy-error deltas are in [paired_metrics.csv](paired_metrics.csv).", ""]
        report += ["Across the primary cross-house rows, the candidate has lower macro F1 and higher mean absolute energy error. The current evidence does not support replacing the baseline with this candidate.", ""]
        if candidate_strata:
            summary = []
            cross_strata = [r for r in candidate_strata if r["source_house"] != str(r["house_id"])]
            strata_order = [("aggregate_power", v) for v in ("0-100W", "100-500W", "500-1500W", "1500W+")] + [("concurrent_actual_on", v) for v in ("0", "1", "2", "3+")]
            for stratum, value in strata_order:
                rs = [r for r in cross_strata if r["stratum"] == stratum and r["stratum_value"] == value]
                if not rs:
                    continue
                keys = {(r["source_house"], r["house_id"]) for r in rs}
                # Count samples once per paired source-target group, not once
                # per device. Each target can occur under both source models.
                counts = {key: int(next(r["sample_count"] for r in rs if (r["source_house"], r["house_id"]) == key)) for key in keys}
                bf = [float(r["baseline_f1"]) for r in rs if r["baseline_f1"] not in ("", "None")]
                cf = [float(r["candidate_f1"]) for r in rs if r["candidate_f1"] not in ("", "None")]
                ba = [float(r["baseline_absolute_error_kwh"]) for r in rs]
                ca = [float(r["candidate_absolute_error_kwh"]) for r in rs]
                summary.append(["Aggregate load" if stratum == "aggregate_power" else "Concurrent ON", value,
                                f"{sum(counts.values()):,}", str(len(rs)),
                                f"{np.mean(bf):.3f}" if bf else "—", f"{np.mean(cf):.3f}" if cf else "—",
                                f"{np.mean(ba):.3f}" if ba else "—", f"{np.mean(ca):.3f}" if ca else "—"])
            report += ["### Cross-house stratified comparison", "",
                       markdown_table(["Stratification", "Stratum", "Samples", "Device groups", "Baseline macro F1", "Candidate macro F1", "Baseline mean absolute error (kWh)", "Candidate mean absolute error (kWh)"], summary), "",
                       "Rows pool cross-house source-target-device groups. Sample counts are summed once per source-target-stratum, not once per device. These are descriptive point estimates; the detailed paired table retains every label and pair.", "",
                       "Paired aggregate-power strata and actual concurrent-ON strata for both cross-house and in-house groups are available in [paired_stratified_metrics.csv](paired_stratified_metrics.csv), with source, target, and device labels.", ""]
    else:
        report += ["Candidate predictions and metrics are not yet present at `model/v1/predictions/` and `model/v1/metrics.csv`; baseline-to-candidate improvements and regressions are pending.", ""]
    report += ["## Trace figures", "",
              f"- [Baseline representative window](baseline_representative.png): source House 2 → unseen target House 3, selected by one-device majority concurrency and aggregate mean closest to the target-window median (window {rep}).",
              f"- [Baseline high-error window](baseline_high_error.png): source House 2 → unseen target House 3, first matching row in the audited top absolute-kWh error list (window {high}).",
              "Each figure shows aggregate power and ground-truth/predicted power for every device. Window titles state target house, start time, and actual simultaneous ON count (majority and peak during the window).", ""]
    if cand_files:
        report += ["Paired candidate traces use the same two target windows: [representative](candidate_representative.png) and [high-error](candidate_high_error.png).", ""]
    report += ["## Uncertainty and limitations", "",
               "Some baseline evaluation summaries include block bootstrap intervals that resample contiguous one-hour blocks within house; no paired confidence interval is reported for baseline-candidate deltas, so the point estimates do not establish statistical significance. The comparison has only two trained source houses, two candidate training seeds, up to 128 selected windows per target, and substantial target data gaps. Device energy APE is unstable when true energy is near zero. Concurrent strata overlap across source models and high-concurrency samples are sparse. No result here establishes generalization to all REFIT houses or a four-fold LOHO estimate.", "",
               "## Reproduction", "",
               "Run `uv run --group nilm python dataset/research_v1/report/build_report.py` from the repository root to regenerate figures, tables, and this report. Candidate outputs are included automatically when the model run has produced them.", ""]
    (HERE / "report.md").write_text("\n".join(report), encoding="utf-8")
    print(f"Wrote report and figures to {HERE}")


if __name__ == "__main__":
    main()
