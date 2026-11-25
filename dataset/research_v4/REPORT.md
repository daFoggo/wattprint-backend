# Research v4: detector variants on REFIT, and homes from Plegma and ENERTALK (2026-11-24)

Same data, split (last 20 % of each home's time), inputs and seeds (11, 22, 33) as research v3 (`context`
variant). Two scores everywhere: **ON/OFF F1** (is the device on, per 15 s step) and **energy F1** (energy matched step by
step) with the kWh error. Raw numbers: `onoff_v4_house{2,5}.json`, `plegma_survey.json`.

## 1. Detector variants (v3 "Next" items): no gain
`onoff_v4.py`: **hardneg** weights the windows where a cross-fitted first pass invented runs; **stack** feeds that first
pass's P(ON) as inputs (the fridge's rhythm); **excl** penalises two of microwave/toaster/kettle being ON together.
Macro ON/OFF F1 (largest per-device seed sd in the last column):

| Home | Variant | Macro F1 | max sd |
|---|---|---|---|
| H5 | context (v3) / re-run | 0.608 / 0.610 | 0.04 |
| H5 | hardneg · stack · excl | 0.602 · 0.559 · 0.610 | 0.04 · 0.09 · 0.05 |
| H2 | context (v3) / re-run | 0.600 / 0.601 | 0.04 |
| H2 | hardneg · stack · excl | 0.589 · 0.593 · 0.604 | 0.08 · 0.03 · 0.03 |

All differences are inside the seed spread; `stack` is worse on House 5. The fridge gained +0.013 from `hardneg` on
House 5 only. The combination `all` was not run: no component helps alone. **Kept: v3's `context` inputs.** The
overcounted fridge kWh in House 2 is not fixed by these changes. Not tried: a per-device fridge detector.

## 2. Datasets
See `docs/nilm-datasets.md`. Plegma (Greece, 13 homes, 10 s, ACs and a boiler) and ENERTALK (Korea, 22 homes, 15 Hz, rice
cooker) suit NILM; PRECON does not (mixed circuit channels, rate unknown); iAWE could not be fetched. Converters:
`scripts/plegma_to_refit.py` (split ACs summed into one `AC`) and `enertalk_to_refit.py`.

Detector only, 3 seeds, macro ON/OFF F1 (first channel layout: Plegma's ACs kept apart, ENERTALK with a water purifier; the json files `research_v3/onoff_train_house{101,103,104,111,200,205}.json`; the homes in section 3 use the merged-AC layout): Plegma H1 0.693 · H3 0.425 · H4 0.501 · H11 0.621 (these three have a device
that is idle in their test part: AC H3 0.02, boiler H4 0.00) · ENERTALK H0 0.698 · H5 0.633.

## 3. Production recipe on the two homes added to the demo (`train_house.py`, 5 seeds, test = last 20 %)

| Home | Device | True kWh | kWh error | Energy F1 | ON/OFF F1 |
|---|---|---|---|---|---|
| Plegma 1 (101) | AC (units added) | 494.5 | −11 % | 0.894 | 0.996 |
| | Boiler | 27.6 | +22 % | 0.882 | 0.993 |
| | Fridge | 93.8 | +9 % | 0.866 | 0.907 |
| | Washer | 0.9 | −4 % | 0.382 | 0.623 |
| | **Macro** | | total −6.3 % | **0.756** | **0.880** |
| ENERTALK 0 (200) | Fridge | 16.1 | −30 % | 0.686 | 0.876 |
| | Kimchi fridge | 1.0 | +47 % | 0.585 | 0.744 |
| | Washer | 4.3 | +22 % | 0.827 | 0.750 |
| | Rice cooker | 2.5 | −2 % | 0.811 | 0.871 |
| | Microwave | 1.4 | −22 % | 0.670 | 0.787 |
| | **Macro** | | total −15 % | **0.716** | **0.805** |

For comparison the shipped REFIT models score energy F1 0.57 (H2) and 0.45 (H5) on their own test part.

## What this does and does not show
- The pipeline works on hot-climate homes with big ACs (energy F1 0.91 for the AC) and on a rice cooker (0.81).
- It does not show transfer: each model is trained and tested on one home's own time. The REFIT cross-home test (a model
  trained on another home) lost a third of its energy F1. The ENERTALK home has 3 months of data (687 windows), Plegma 1
  has 15 months. Washer scores are weak where it runs rarely (Plegma 1: 0.9 kWh in the test part).
- No Vietnamese recording exists in public; nothing here claims accuracy in Vietnam.

## Next
1. Leave-one-home-out with fine-tuning on 1–7 days of the new home, on Plegma + ENERTALK + REFIT: the data-efficiency
   curve that decides how much Vietnamese data a pretrain stage needs.
2. A small measurement kit for Vietnamese homes (aggregate + plug on AC, rice cooker, fridge), 2–4 weeks each.
