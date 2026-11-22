# NILM evaluation CLI

Run from any working directory with NumPy available:

```bash
python dataset/research_v1/evaluation/evaluate.py predictions.npz --out-dir results
```

The NPZ needs row-aligned `house_id`, `timestamp`, `aggregate_w`, `y_true_w`,
`y_pred_w`, `labels`, and scalar `sample_seconds`. Power arrays have shape
`(N, C)` for `C` labels. `house_id` may be a scalar or one value per sample.
Timestamps may be NumPy datetimes, ISO datetime strings, or numeric epoch
seconds. Multiple input files can be evaluated together if labels, their order,
and sampling period match.

Optional `p_on` supplies ON probabilities. Optional `event_thresholds` supplies
one probability cutoff per label (or one scalar). When `p_on` is available but
thresholds are absent, the CLI uses 0.5; `--event-threshold` overrides that.
F1 is based on actual power ON thresholds: REFIT label defaults are included in
the CLI, unknown labels use 50 W by default, and `--on-threshold LABEL=WATTS`
can override either. F1 compares actual ON state with the probability-based
predicted state when `p_on` is present; otherwise it compares actual and
predicted power using the same ON threshold. Both true and predicted contiguous
ON event counts are reported.

Outputs are `house_device_metrics.csv`, `stratified_metrics.csv`, and
`summary.json`; `--prefix NAME` prepends a name to each output filename.
Energies integrate sample power using `sample_seconds`; signed
error is predicted minus true kWh, absolute error is its magnitude, and percent
error divides that magnitude by true kWh (null when true energy is zero). F1 is
null when both true and predicted ON sets are empty, and zero when false
positives occur without true ON samples. Macro F1 omits null values; macro
percentage error omits zero-energy groups. Very small nonzero true energy can
make percentage error unstable, so inspect absolute kWh error as well. The
strata use aggregate power bands 0–100, 100–500, 500–1500, and 1500+ W, plus
concurrent actual ON device counts 0, 1, 2, and 3+. The bootstrap resamples
contiguous fixed-duration blocks within each house and reports percentile 95%
intervals for macro device F1 and absolute percentage energy error.

Set `--bootstrap-iterations 0` to skip uncertainty estimation. The random seed,
block duration, and iteration count are recorded in the summary.
