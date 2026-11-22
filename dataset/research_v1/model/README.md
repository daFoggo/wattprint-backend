# Research model v1

This directory contains a bounded aggregate-sensor augmentation experiment and its paired held-out predictions. It uses the backend-supported `GRUDetector` plus `NILMFormerRegressor` ensemble. The generalization intervention applies a random 0.9–1.1 gain and 15 W standard deviation Gaussian noise to aggregate input during training only; appliance labels and calendar features stay unchanged. This targets modest aggregate meter calibration drift while preserving the deployed architecture.

## Reproduce

From the repository root:

```bash
uv run --group nilm python dataset/research_v1/model/run.py --max-windows 128
```

The trainer fits independent House 2 and House 5 bundles. For each source, it trains two fixed seeds on the temporal train partition, samples at most 512 source windows per epoch, selects the common final epoch as the median source-validation best epoch, and refits those seeds on all source windows before the test partition (including the former train/validation gap). Event thresholds are selected per label from source validation probabilities. No held-out target data is used for fitting or tuning. Once checkpoints and thresholds are frozen, the script evaluates the exact House 2/3/5/6 window indices in `../baseline/manifest.json`.

`v1/houseN/nilm_pipeline.pt` contains the two final trained members. `v1/houseN/metadata.json` records architecture, seeds, splits, selected epochs, thresholds, and checkpoint hash. `predictions/sourceN_targetM.npz` uses the baseline NPZ schema and adds `event_thresholds`; the arrays `house_id`, `timestamp`, `aggregate_w`, `y_true_w`, `y_pred_w`, `labels`, and `sample_seconds` are directly consumable by `../evaluation/evaluate.py`. The `metrics.csv` values use the same target windows as the baseline, with ON/OFF F1 evaluated using each model's source-validation thresholds.

## Standalone preprocessing and inference

The `preprocess.py` helper implements the dataset contract without importing `app/`: drop issue rows, clip aggregate/appliance channels to 0–10,000 W with values under 5 W zeroed, take 15-second means, discard nonfinite bins and any window crossing a gap, and construct aggregate plus wall-clock time features. Run a real CSV example with:

```bash
uv run --group nilm python dataset/research_v1/model/inference_example.py \
  --house 3 --csv dataset/CLEAN_House3.csv \
  --checkpoint dataset/research_v1/model/v1/house2/nilm_pipeline.pt
```

## `wattprint-nilm/2` inference contract

The standalone loader in `inference.py` and vendored definitions in `architecture/` need only NumPy and PyTorch. The checkpoint uses the same `wattprint-nilm/2` contract as `app.modules.nilm.services.engine.load`: 256 samples at 15-second intervals, float32 input shaped `(B, 9, 256)`, aggregate watts followed by eight wall-clock time sine/cosine features. `Bundle.predict` accepts `(B, 9, 256)` and returns appliance watts shaped `(B, C, 256)` in checkpoint label order. `Bundle` also exposes `event_thresholds` and the model hash.

Example:

```python
import numpy as np
from dataset.research_v1.model.inference import load

bundle = load("dataset/research_v1/model/v1/house2/nilm_pipeline.pt")
x = np.zeros((1, 9, 256), dtype=np.float32)  # replace with preprocessed aggregate + time features
appliance_w = bundle.predict(x)
print(bundle.labels, appliance_w.shape)  # (1, C, 256), watts
```

The example's zero input is only a shape demonstration. For a real CSV to prediction path, use `inference_example.py` above. The backend can also load the same `wattprint-nilm/2` checkpoint through its own engine.

## Scope

This is source-house transfer evaluation, not four-fold leave-one-house-out evaluation. Each target's temporal test partition is held out from all training and threshold tuning, but a source model may have been trained on that same house when source equals target. Cross-house rows measure transfer to unseen houses. House 6 Freezer is reported as a distinct label and is excluded when absent from the source label set.

## Exploratory results

Neither candidate is recommended as an improvement. Across the 34 v1 cross-house device rows, the augmented models had macro ON/OFF F1 0.265 versus 0.421 for the original bundles, and mean absolute kWh error 1.785 versus 1.024. The augmentation changed both the input perturbation and the training budget, so this is an exploratory comparison rather than causal evidence about augmentation alone.

`v2_source_blend/` is a fixed equal-weight blend of the frozen original House 2 and House 5 bundles, evaluated only on unseen Houses 3 and 6. Its ON decision is `mean(p_source / source_validation_threshold) >= 1`, stored as `p_on = score / (1 + score)` with cutoff 0.5. On House 3 the blend macro F1 / mean absolute kWh error were 0.412 / 0.805, between the source 2 values 0.445 / 0.435 and source 5 values 0.319 / 1.564. On House 6 they were 0.462 / 0.430, between source 2 values 0.477 / 0.620 and source 5 values 0.446 / 0.260. The blend trades errors across sources and does not dominate either; its copied checkpoints and standalone inference wrapper are retained as an exploratory artifact.

The v1 standalone loader matched `app.modules.nilm.services.engine` exactly (maximum absolute output difference 0 W) on a real 256-sample held-out window reconstructed from the baseline NPZ's aggregate and timestamps. The standalone calendar-feature helper also matched `dataset.training.train_house.time_features` exactly on that window. The v2 standalone blend output differed from its saved baseline-derived prediction by at most 0.016 W on the same real window.

## Backend integration later

The v1 checkpoint has the existing `wattprint-nilm/2` format and can be loaded by the current backend bundle loader after a separate deployment decision. Supply the checkpoint path, preserve its ordered `labels`, 15-second sampling, 256-step windows, nine input channels, and source-validation `event_thresholds`; the backend already computes the two-stage detector/regressor output for this format. The current experiment does **not** support replacing the production bundle.

The v2 blend directory is **not** itself a `wattprint-nilm/2` bundle. To integrate it later, load both copied `weights/house2.pt` and `weights/house5.pt`, run both bundles on the same `(B, 9, 256)` input, align their outputs by label, and average appliance watts. For ON/OFF, compute each source detector ensemble probability, divide each by its own stored event threshold, average the two ratios, and classify ON when that average is at least 1. `blend_inference.py` implements this interface and returns `(watts, score/(1+score))`, where 0.5 is the equivalent ON cutoff. The existing backend `Bundle.predict` returns only watts, so a future backend change would have to expose detector probabilities and add this two-source composition. No backend file was changed here; the blend is also not recommended from the present results.
