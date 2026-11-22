# REFIT NILM research v1: preliminary results

## Scope and protocol

This report summarizes the frozen baseline and, when present, paired candidate predictions. The current experiment evaluates source House 2 and House 5 models on temporal test windows from Houses 2, 3, 5, and 6. Source-equals-target rows are in-house temporal tests; source-differs-from-target rows are cross-house transfer. **This is not a true leave-one-house-out (LOHO) experiment:** only Houses 2 and 5 are trained as sources, so Houses 3 and 6 are never held out as one of four folds with all other houses used for training. The protocol README describes LOHO as a plan; the results here must not be described as LOHO.

The protocol audit records 15-second data, removes `Issues=1` rows, and notes long missing spans. Test windows are selected from the target temporal test partition and held fixed across source models. House 6 uses a Freezer channel where other houses use Fridge; those labels are not equivalent and are excluded from direct fridge comparisons.

## Baseline overview

| Source → target | Evaluation | Mean device F1 | Mean device energy APE |
|---|---|---|---|
| 2 → 2 | in-house temporal test | 0.656 | 20.8% |
| 2 → 3 | cross-house transfer | 0.445 | 85.7% |
| 2 → 5 | cross-house transfer | 0.455 | 38.7% |
| 2 → 6 | cross-house transfer | 0.477 | 12331.7% |
| 5 → 2 | cross-house transfer | 0.395 | 278.2% |
| 5 → 3 | cross-house transfer | 0.319 | 956.3% |
| 5 → 5 | in-house temporal test | 0.538 | 13.3% |
| 5 → 6 | cross-house transfer | 0.446 | 3444.8% |

The means above average device-level scores equally within each source-target group. APE can be dominated by near-zero energy devices, so read it with F1, absolute kWh error, and sample/on counts rather than alone.

## Concurrent-load stratification

| Actual concurrently ON | Sample count across source-target evaluations | Macro device F1 | Mean absolute device energy error (kWh) |
|---|---|---|---|
| 0 | 161,078 | 0.000 | 0.731 |
| 1 | 89,654 | 0.488 | 0.755 |
| 2 | 10,960 | 0.556 | 0.396 |
| 3+ | 452 | 0.531 | 0.045 |

Counts and metrics are pooled over the eight source-target evaluations, so each target window appears once per source model. The 3+ stratum is sparse; these summaries are descriptive and are not independent observations.

## Paired candidate comparison

| Comparison | Matched device groups | Baseline macro F1 | Candidate macro F1 | Baseline mean absolute error (kWh) | Candidate mean absolute error (kWh) | Candidate delta absolute error |
|---|---|---|---|---|---|---|
| Cross-house transfer (primary) | 34 | 0.421 | 0.265 | 1.024 | 1.785 | +0.761 |
| In-house temporal test | 12 | 0.597 | 0.346 | 0.515 | 0.615 | +0.100 |

Primary cross-house transfer comparison: 34 matched source-target-device groups; candidate F1 improved in 7, regressed in 25; absolute energy error improved in 6, regressed in 28. In-house temporal test rows are reported separately (12 groups). These results do not isolate an augmentation effect: the candidate used two training seeds, and there is no matched unaugmented retraining control; training budget and seeds also differ from the baseline. Per-group F1 and energy-error deltas are in [paired_metrics.csv](paired_metrics.csv).

Across the primary cross-house rows, the candidate has lower macro F1 and higher mean absolute energy error. The current evidence does not support replacing the baseline with this candidate.

### Cross-house stratified comparison

| Stratification | Stratum | Samples | Device groups | Baseline macro F1 | Candidate macro F1 | Baseline mean absolute error (kWh) | Candidate mean absolute error (kWh) |
|---|---|---|---|---|---|---|---|
| Aggregate load | 0-100W | 4,086 | 34 | 0.000 | 0.000 | 0.025 | 0.035 |
| Aggregate load | 100-500W | 138,820 | 34 | 0.200 | 0.118 | 0.320 | 0.685 |
| Aggregate load | 500-1500W | 41,890 | 34 | 0.342 | 0.166 | 0.214 | 0.444 |
| Aggregate load | 1500W+ | 11,812 | 34 | 0.498 | 0.310 | 0.787 | 1.316 |
| Concurrent ON | 0 | 128,612 | 34 | 0.000 | 0.000 | 0.759 | 1.175 |
| Concurrent ON | 1 | 60,615 | 34 | 0.454 | 0.305 | 0.835 | 1.193 |
| Concurrent ON | 2 | 7,080 | 34 | 0.516 | 0.399 | 0.433 | 0.616 |
| Concurrent ON | 3+ | 301 | 34 | 0.439 | 0.339 | 0.043 | 0.063 |

Rows pool cross-house source-target-device groups. Sample counts are summed once per source-target-stratum, not once per device. These are descriptive point estimates; the detailed paired table retains every label and pair.

Paired aggregate-power strata and actual concurrent-ON strata for both cross-house and in-house groups are available in [paired_stratified_metrics.csv](paired_stratified_metrics.csv), with source, target, and device labels.

## Trace figures

- [Baseline representative window](baseline_representative.png): source House 2 → unseen target House 3, selected by one-device majority concurrency and aggregate mean closest to the target-window median (window 120).
- [Baseline high-error window](baseline_high_error.png): source House 2 → unseen target House 3, first matching row in the audited top absolute-kWh error list (window 65).
Each figure shows aggregate power and ground-truth/predicted power for every device. Window titles state target house, start time, and actual simultaneous ON count (majority and peak during the window).

Paired candidate traces use the same two target windows: [representative](candidate_representative.png) and [high-error](candidate_high_error.png).

## Uncertainty and limitations

Some baseline evaluation summaries include block bootstrap intervals that resample contiguous one-hour blocks within house; no paired confidence interval is reported for baseline-candidate deltas, so the point estimates do not establish statistical significance. The comparison has only two trained source houses, two candidate training seeds, up to 128 selected windows per target, and substantial target data gaps. Device energy APE is unstable when true energy is near zero. Concurrent strata overlap across source models and high-concurrency samples are sparse. No result here establishes generalization to all REFIT houses or a four-fold LOHO estimate.

## Reproduction

Run `uv run --group nilm python dataset/research_v1/report/build_report.py` from the repository root to regenerate figures, tables, and this report. Candidate outputs are included automatically when the model run has produced them.
