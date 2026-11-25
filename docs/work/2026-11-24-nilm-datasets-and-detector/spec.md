# Spec: NILM detector research v4 and external datasets

## Requirements
R1 Every number is on each house's own test split (last 20 %), seeds 11/22/33, same data and split as
   `dataset/training/train_house.py`; baseline = research_v3 `context` variant, re-run in v4 so seeds match.
R2 Two scores are always reported together: ON/OFF F1 (state) and energy F1 plus kWh error (pipeline_eval, split gate).
R3 Experiments, in this order, each stopping if it cannot beat the baseline by more than seed sd:
   E1 hard negatives: second detector pass trained with the stretches where the first pass invented runs up-weighted.
   E2 fridge rhythm: input "time since the last called run" from the first pass (cycle period), fridge head only.
   E3 short heaters (kettle, toaster, microwave): exclusion penalty or softmax so two are not ON at one switch-on.
   E4 the best combination, scored with `pipeline_eval` (energy F1, kWh error) on both houses.
R4 Datasets: for Plegma, PRECON and at least five more candidates: sampling rate, ground truth (plug vs circuit),
   appliances, climate fit to Vietnam, licence, how to get it, verdict "NILM-suitable: yes / partly / no" with the reason.
R5 Converter for the best suitable dataset: aggregate and per-appliance plugs to 15 s, REFIT column names, `Issues` flag,
   same clip rules as `train_house.load`; unit test on a synthetic file. Real run only once the archive is on disk.
R6 Report `dataset/research_v4/REPORT.md` (results, negative results included) and `docs/nilm-datasets.md`.
R7 Nothing ships: no change to `app/`, the shipped bundles or the certainty levels (Cao/Vừa/Thấp thresholds stay).

## Areas of concern
- Test split is the last 20 % of one house: seed sd and a single split can fake gains; report sd, not only means.
- Plegma has no kettle/microwave/toaster list verified (Table 3 unread): the label set may differ from REFIT's six.
- Plegma sync error: appliances can lead/lag the aggregate by 2–3 samples; flagged `issues` rows are dropped like REFIT's.
- Hot-climate gain is a hypothesis: a dataset can suit NILM yet not transfer to a Vietnamese home (voltage 230 V 50 Hz
  matches; AC inverter behaviour differs). The report says so; no claim of transfer to Vietnam.
- GPU shared with running services (NILM worker): train with a bounded batch, check `nvidia-smi` first.

## Scope of this change (files)
Backend: `scripts/plegma_to_refit.py`, `scripts/enertalk_to_refit.py`, their tests, `dataset/training/train_house.py`
(CHANNELS 101/200/205, thresholds), `dataset/research_v4/*`, `app/modules/nilm/services/devices.py` (DEVICE_TYPES),
`alembic/versions/public/20261124_d9a4e6b2c751_rice_cooker_device_type.py`, `scripts/demo_homes.toml` (two homes added,
the House 5 heater home removed), `docs/nilm-datasets.md`. Web: `device-icon.tsx`, `features/energy/queries.ts`,
`messages/*/energy.json`. The rest of the diff since the base is the earlier demo-readiness change (already reviewed).
Ran, not in the diff: the heater home's rows were deleted from the dev database (readings, meter, home, owner row).
