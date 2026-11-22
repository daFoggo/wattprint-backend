# REFIT cross-house NILM research v1

The follow-up backbone and calibration experiments are in
[dataset/research_v2/REPORT.md](../research_v2/REPORT.md).

The executed experiment and its limits are in [report/report.md](report/report.md).
The current candidate did not improve unseen-house transfer, so no checkpoint
in this directory is recommended for production replacement.

## Reproduce from the repository root

```bash
uv run python dataset/research_v1/protocol/audit.py
uv run --group nilm python dataset/research_v1/baseline/run.py --max-windows 128
uv run --group nilm python dataset/research_v1/model/run.py --max-windows 128
uv run --group nilm python dataset/research_v1/model/blend.py
uv run --group nilm python dataset/research_v1/concurrent/analyze.py --candidate-dir dataset/research_v1/model/predictions
uv run --group nilm python dataset/research_v1/report/build_report.py
```

Evaluate an individual prediction artifact, including a seeded one-hour block
bootstrap, with:

```bash
uv run python dataset/research_v1/evaluation/evaluate.py \
  dataset/research_v1/baseline/source2_target3.npz \
  --out-dir dataset/research_v1/evaluation/results \
  --prefix source2_target3_ --bootstrap-iterations 200 --seed 17
```

The reference bundles remain in `dataset/models/nilm/house{2,5}/`. New weights,
standalone architecture and inference examples are in [model/README.md](model/README.md).
The evaluated subset is a group split by source/target house with paired
temporal-test windows; it is **not** a full four-fold leave-one-house-out run.
The held-out target house contributes no training, tuning, normalization or
post-processing statistics to the corresponding cross-house comparison.

The `baseline/`, `evaluation/`, `concurrent/`, `model/`, `protocol/`, and
`report/` directories each hold their scripts and machine-readable results.
No large REFIT CSV or intermediate training checkpoint is copied here.
