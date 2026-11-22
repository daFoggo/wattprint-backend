# Concurrent ON-load analysis

Run from the repository root:

```sh
uv run python dataset/research_v1/concurrent/analyze.py
```

This reads the eight House 2/5 source to House 2/3/5/6 baseline NPZs and writes
`stratum_counts.csv`, `stratum_metrics.csv`, `high_error_cases.csv`, and
`summary.json` in this directory. Every row corresponds to a 15-second sample
from the existing held-out test windows.

## Definition

For each row, actual concurrent ON count is the number of comparable labeled
channels whose truth power meets the training ON threshold: Fridge/Freezer 50 W,
WashMach 20 W, Dishwash 10 W, Microwave/Toaster 200 W, and Kettle 1000 W.
Counts are grouped into 0, 1, 2, and 3+ strata. Each stratum count is reported
for a source/target pair; metrics then report energy and ON/OFF F1 for each
device within that stratum. F1 uses `p_on` at the source bundle's frozen event
threshold (recorded in `summary.json` and embedded in the CLI); prediction files
with `event_thresholds` use those values. Prediction files without `p_on` use
predicted watts at the actual ON threshold.

High-error cases rank individual 256-sample window/device pairs within each
source/target/model by absolute kWh error. The category identifies missed ON,
false ON, or amplitude over/underestimation relative to the same frozen
thresholds. By default the top 200 cases per file are emitted.

To analyze a new set of predictions on identical windows, pass both directories:

```sh
uv run python dataset/research_v1/concurrent/analyze.py \
  --reference-dir dataset/research_v1/baseline \
  --candidate-dir dataset/research_v1/improved
```

The command rejects a candidate file if its timestamps, aggregate, truth,
sample duration, or label order differs from the reference. The CSVs identify
rows as `reference` or `candidate`, allowing paired comparisons without
reselecting windows.

Energy percentage error can be very large in the zero- or one-device strata
because true energy there may be close to zero; use absolute kWh error and F1
alongside percentage error. Empty 3+ strata are retained in the count output
and do not contribute an undefined F1 to macro summaries.
