# NILM dual-branch backbone study

## Hypothesis and literature

The two-model design remains: an ON/OFF detector estimates per-appliance
probabilities and a conditional regressor estimates watts, multiplied at
inference. This follows the classification-regression gating idea in
[Subtask Gated Networks](https://arxiv.org/abs/1811.06692) and the broader
[hybrid classification-regression study](https://arxiv.org/abs/2208.10638).

The new backbones are six residual temporal-convolution blocks with dilations
1, 2, 4, 8, 16, 32 and a 253-sample receptive field. Convolutional sequence
models learn appliance signatures in [sequence-to-point NILM](https://arxiv.org/abs/1612.09106),
while [NILMFormer](https://arxiv.org/abs/2506.05880) motivates explicit care
with within-window nonstationarity. Input features therefore include aggregate
power, its stepwise difference, and power centered on the window median,
alongside eight fixed calendar features. The detector and regressor have
separate backbones and can be ablated independently.

The v2.1 experiment also tries label-preserving residual-background
recomposition on source-house training batches, motivated by
[Liu and Fan (2026)](https://arxiv.org/abs/2609.18315). It replaces only the
unmodeled aggregate residual with another source-window residual. This is a
training-time perturbation; it adds no inference module. Its contribution
cannot be isolated from the simultaneous loss and validation changes without
a matched ablation.

## Protocol

Four outer folds hold out House 2, 3, 5, or 6 in turn. Each fold fits on the
other three houses. One source house with a Fridge label serves as grouped
inner validation; the initial fit uses the other two sources. Stopping epoch,
ON cutoffs, and the v2.1 energy scale are selected from that source-only
validation house. The final two fixed seeds (11, 22) refit on all three source
houses for the selected epoch count. The held-out target contributes no fit,
normalization, threshold, or postprocessing statistic. Prediction windows are
the exact 128 per-house temporal-test windows from
`dataset/research_v1/baseline/manifest.json`, enabling row-aligned comparisons.

The six output heads are Fridge, WashMach, Dishwash, Microwave, Toaster, and
Kettle. House 6's Freezer is not a Fridge: its Fridge loss is masked during
training and its Fridge head is excluded from evaluation. Freezer is an
unknown class to this model, so no Freezer F1 is claimed. ON thresholds in
watts match `dataset/training/train_house.py`.

The v2.0 baseline uses event-enriched validation and a positive-only
conditional regressor loss; it is retained as a failed ablation. v2.1 uses
natural time-spaced source validation, penalizes idle conditional power, and
calibrates energy from the inner validation house only. The changes were
informed by the v2.0 diagnostic run; v2.1 outer-test comparisons are
exploratory and should be confirmed on additional houses before deployment.

## Artifacts and compatibility

- `architecture.py`: detector and regressor definitions and exact feature transform.
- `preprocess.py`: REFIT CSV to non-gap, 15-second, 256-step inputs.
- `inference.py`: checkpoint loader returning ON probabilities and appliance watts.
- `run.py`: v2.0 fold trainer; `run_v21.py`: v2.1 fold trainer.
- `weights/`, `predictions/`, `metrics.csv`: v2.0 results.
- `v2_1/weights/`, `v2_1/predictions/`, `v2_1/metrics.csv`: v2.1 results.

The format `wattprint-nilm-tcn/1` differs from production
`wattprint-nilm/2`. A future backend integration would add a loader for
`TCNDetector` and `TCNRegressor`, pass `(B,9,256)` float32 inputs with
aggregate watts and eight wall-clock features, and apply the stored
`power_scale_w`, `energy_calibration`, and label order. The standalone
`Bundle.predict` returns `(probability, watts)` each `(B,C,256)`; use the
stored `event_thresholds` for ON/OFF. The backend must also preserve the
15-second cadence and avoid windows across missing-data spans. This research
does not modify the backend or production bundles.

### Commands

```bash
uv run --group nilm python dataset/research_v2/run.py --epochs 8 --windows-per-epoch 256 --device cpu
uv run --group nilm python dataset/research_v2/run_v21.py --epochs 16 --windows-per-epoch 512 --device cpu
uv run --group nilm python dataset/research_v2/inference.py dataset/research_v2/v2_1/weights/loho_target3_v2.1.0.pt --csv dataset/CLEAN_House3.csv --house 3
```

`--device auto` uses CUDA only when at least 4 GiB is free; the recorded runs
used CPU because the shared GPU was occupied. Checkpoint manifests record the
exact seeds, fold composition, epochs and per-fold SHA-256 hashes.
