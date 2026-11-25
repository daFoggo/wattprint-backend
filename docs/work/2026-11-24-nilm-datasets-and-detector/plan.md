# Plan

Base: backend HEAD `21fe144` (dirty tree: the demo-readiness work, snapshot taken before R1).

| # | Task | Files | Proof | Standards |
|---|---|---|---|---|
| 1 | Dataset survey (R4): fetch what can be read, write verdicts | `docs/nilm-datasets.md` | each row cites its source; unverified marked | none (docs) |
| 2 | Baseline re-run `context`, 3 seeds, both houses | `dataset/research_v4/run_base.py` reuses v3 `onoff_train.py` | numbers match v3 within sd | ruff on new .py |
| 3 | E1 hard negatives | `research_v4/hardneg.py` | macro ON/OFF F1 vs task 2, sd | ruff |
| 4 | E2 fridge rhythm | `research_v4/rhythm.py` | fridge F1/precision vs task 2 | ruff |
| 5 | E3 short heaters | `research_v4/heaters.py` | toaster/microwave/kettle F1 vs task 2 | ruff |
| 6 | E4 best combination + `pipeline_eval` | `research_v4/combine.py` | energy F1 + kWh err, both houses | ruff |
| 7 | Converter + test (R5) | `scripts/plegma_to_refit.py`, `tests/test_plegma_to_refit.py` | test red then green on synthetic data | ruff, tests |
| 8 | Report (R6) | `research_v4/REPORT.md` | every number traceable to a json | none |
| 9 | Review loop R1 (opus) → fix → R2 if Should-fix open | `review.md` | verdicts | sdlc §3 |

Risks: GPU contention; no gain (negative result is still reported); Plegma not downloadable (task 7 stays synthetic).
Order: 1 and 2 first (cheap), 3–6 sequential (GPU), 7 while training runs.

## Added 2026-11-24 (user, mid-run)
- 10 Delete the "REFIT-H5-heat" demo home (House 5 with the simulated heater) from the database.
- 11 Add at most 2 homes from the best external datasets (candidate: Plegma houses 101/104, ENERTALK 205/200) and train
  one per-house NILM model for each (`train_house.py --house N` -> `dataset/models/nilm/house<N>/`).
  Needs: DEVICE_TYPES for AC/boiler/rice cooker, seed + replay of the new homes (see `scripts/` for REFIT homes).
- Results so far: v4 detector variants (hardneg, stack, excl) gave no gain on REFIT H2/H5 (within seed sd);
  Plegma H101 baseline detector macro ON/OFF F1 0.693; converters `plegma_to_refit.py`, `enertalk_to_refit.py` tested.
- Training run in background writes `/tmp/plegma_run.log` (houses 103, 104, 111 detector; full train 101, 104).
