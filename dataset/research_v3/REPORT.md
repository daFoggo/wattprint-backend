# Research v3: the ON/OFF detector first (2026-11-24)

Question (team, 2026-11-24): the pipeline is a detector (ON/OFF mask) then a regressor (power where ON), the
regressor's loss flows back into the detector, and auto-on devices (the fridge) suffer. Improve ON/OFF first, the
regressor after. Every number below is on each house's own test split (last 20 %), same data and split as
`dataset/training/train_house.py`; seeds 11, 22, 33 unless said.

## Step 1: post-processing the shipped bundles, no retraining (`onoff_post.py`)
Test cut in two by time: tune on the first half, score on the second.
- Hysteresis and minimum ON/OFF durations change ON/OFF F1 by at most ±0.02 (fridge 0.711 → 0.712 House 5,
  0.784 → 0.783 House 2): the detector's errors are not flicker around one cut.
- A hard gate (power where P(ON) ≥ the cut) instead of the shipped soft gate (P(ON) × power) raises energy F1 on
  every device but overcounts the fridge's kWh (+51 % House 5, +37 % House 2): the soft gate was hiding the
  detector's false ONs.

## Step 2: the detector retrained alone, in variants (`onoff_train.py`)
Macro ON/OFF F1, mean of 3 seeds (fridge's F1 sd ≤ 0.02):

| Variant | House 5 | House 2 | Fridge H5 (P / R) | Fridge H2 (P / R) |
|---|---|---|---|---|
| joint (the production recipe: gated loss into the detector) | 0.492 | 0.582 | 0.666 (0.53 / 0.91) | 0.704 (0.57 / 0.93) |
| base (detector alone, focal loss) | 0.560 | 0.591 | 0.846 (0.78 / 0.93) | 0.728 (0.59 / 0.95) |
| baseload (+ 15-min rolling floor and the aggregate above it) | **0.591** | **0.595** | 0.845 | 0.733 (0.64 / 0.86) |
| clean (training labels without runs under 2 min fridge / 30 s) | 0.562 | 0.584 | 0.857 | 0.730 |
| long (window 512) | 0.521 | 0.559 | 0.831 | 0.735 |

The regressor's loss flowing into the detector is what hurts: the fridge's precision falls from 0.78 to 0.53 in
House 5 (P(ON) learns the power ratio, not the state), the washing machine 0.34 → 0.21. The toaster in House 2 is
the one device it helps (0.41 → 0.56). The base-load inputs add +0.03 macro in House 5 (washing machine +0.08).

## Step 3: does it carry to energy? (`pipeline_eval.py`)
`split` = the base-load detector alone + the regressor alone (its own loss, power where ON), with a hard gate (a
soft gate is meaningless there: the regressor gives ON power everywhere). Mean of 3 seeds:

| Pipeline, gate | House 5 energy F1 / mean abs kWh err | House 2 |
|---|---|---|
| joint, soft (as shipped) | 0.42 / 28 % | 0.50 / 11 % |
| joint, hard | 0.49 / 20 % | 0.59 / 29 % |
| split, hard (cut by ON/OFF F1 on val) | **0.53 / 15 %** | 0.55 / 18 % |
| split, hard (cut by energy F1 on val) | 0.53 / 19 % | 0.55 / 20 % |

House 5: better on both. House 2: energy F1 better, kWh worse, from two devices: fridge +45 % (precision 0.64:
false ONs at full compressor power) and toaster +39 %. Choosing the cut by energy instead of ON/OFF F1 does not fix
it.

## Step 4: where the extra kWh comes from (`overcount.py`, House 2, seed 11, split pipeline)
Predicted kWh split by the plug's state on the steps the detector calls ON:

| Device | Plug kWh | Pred kWh | Pred on false ON | ... of it within 2 min of a true ON | False ON share | Mean W pred / plug when truly ON |
|---|---|---|---|---|---|---|
| Fridge | 78.9 | 121.0 | 47.6 | 3.5 | 0.39 | 90 / 88 |
| Washing machine | 36.9 | 27.2 | 16.1 | 1.0 | 0.62 | 375 / 351 |
| Dishwasher | 140.7 | 133.4 | 21.4 | 0.4 | 0.22 | 737 / 850 |
| Microwave | 7.8 | 9.7 | 5.2 | 0.8 | 0.53 | 1030 / 931 |
| Toaster | 3.1 | 3.5 | 2.1 | 0.1 | 0.60 | 954 / 917 |
| Kettle | 45.1 | 41.7 | 3.5 | 0.8 | 0.09 | 2762 / 2643 |

- The regressor's power is right when the device is ON (fridge 90 W vs 88 W; others within 5–15 %). The whole
  overcount is the detector's false ONs: the team's order (ON/OFF first, regressor after) is confirmed.
- The false ONs are whole invented runs, not smeared edges (fridge: 3.5 of 47.6 kWh within 2 min of a true run), so
  hysteresis or edge trimming cannot fix them (as step 1 found).
- Short devices (washing machine, microwave, toaster) both invent runs and miss real ones, which cancel in kWh.

## Step 5: what the detector sees when it invents a run (`invented_runs.py`, same seed, no retraining)
At each called run's start: the aggregate's step (4 steps after minus 4 before), another metered device switching ON
within 30 s, the aggregate's level.

| Device, runs | Count | Step W median (p25–p75) | Another device ON | Aggregate W median | Length min median |
|---|---|---|---|---|---|
| Fridge real | 1718 | 44 (2–72) | 0.07 | 254 | 15.8 |
| Fridge invented | 1172 | 10 (0–61) | 0.11 | 348 | 3.5 |
| Toaster real | 50 | 780 (284–861) | 0.08 | 1215 | 1.8 |
| Toaster invented | 109 | 611 (198–905) | **0.81** | 1195 | 0.8 |
| Microwave invented | 176 | 723 (−34–1300) | 0.30 | 1591 | 0.8 |

- Fridge: most invented runs start with no step (median +10 W) while the aggregate sits ~100 W higher than at real
  starts: the detector reads a raised base load as the compressor. By kWh the long ones matter (runs ≥ 15 min hold
  31 of 44 invented kWh), so a minimum run length barely helps (8 min: kWh +31 % → +26 % on the scored half, energy
  F1 unchanged). They are not plug outages: windows where the fridge plug never runs hold 4 of 44 kWh.
- Toaster: 81 % of its invented runs start when another metered device switches ON: it is confused with another
  short heater, not guessing.

## Step 6: a longer floor as input (`onoff_train.py --variants context`)
The aggregate's rolling floor over 2 h and 6 h, taken over the whole series (a 64-min window cannot see them), beside
the 15-min floor, plus the aggregate above the 2-h floor. Macro ON/OFF F1, 3 seeds: House 2 0.595 → 0.600 (fridge
0.733 → 0.750, P 0.64 → 0.63, R 0.86 → 0.92), House 5 0.591 → 0.608 (fridge 0.845 → 0.861, microwave and kettle
up). A small, consistent gain on both houses, but the fridge's precision in House 2 does not move: the raised base is
not what fools it. The edge channel (first difference) was already an input.

## Next
1. Detector, fridge: precision in House 2 (0.63) is untouched by base-level inputs (step 6). Next candidates: the
   fridge's own rhythm (time since the last called run, a cycle-period input), training negatives from the stretches
   where it invents runs, or a per-device detector for the fridge alone. Keep `context` as the inputs (+0.01–0.02).
2. Detector, short heaters (toaster, microwave, kettle): one device per switch-on (they rarely start in the same
   15 s): a softmax over the short heaters at each step, or a penalty when two are called ON together.
3. Regressor: no work needed for kWh (ON power within 5–15 % in step 4).
4. To ship: the bundle format gains the detector's inputs (`baseload`) and a hard gate with per-device cuts; the
   worker's engine builds the same inputs; `scripts/eval_nilm.py` scores ON/OFF F1 too.
