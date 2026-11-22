# REFIT multi-house audit and evaluation protocol

This folder records the data audit and a leakage-safe leave-one-house-out (LOHO)
evaluation plan for REFIT Houses 2, 3, 5, and 6. The audit is reproducible with
`uv run python dataset/research_v1/protocol/audit.py` from the repository root;
its generated result is `audit.json`.

## CSV scope and channel map

Each `CLEAN_HouseN.csv` has `Time`, `Unix`, `Aggregate`, `Appliance1` through
`Appliance9`, and `Issues`. The audit reads only `Time`, `Aggregate`, the mapped
appliance channels, and `Issues`. Appliance labels follow the REFIT cleaned
channel mapping documented in `dataset/training/train_house.py` (its comment
references `CLEAN_READ_ME_081116.txt` and NILMTK meter metadata). The CSVs are
local inputs and are not copied into this protocol folder.

| House | Fridge / Freezer | WashMach | Dishwash | Microwave | Toaster | Kettle |
|---|---|---|---|---|---|---|
| 2 | Fridge `Appliance1` | `Appliance2` | `Appliance3` | `Appliance5` | `Appliance6` | `Appliance8` |
| 3 | Fridge `Appliance2` | `Appliance6` | `Appliance5` | `Appliance8` | `Appliance1` | `Appliance9` |
| 5 | Fridge `Appliance1` | `Appliance3` | `Appliance4` | `Appliance7` | `Appliance9` | `Appliance8` |
| 6 | Freezer `Appliance1` | `Appliance2` | `Appliance3` | `Appliance6` | `Appliance8` | `Appliance7` |

House 6 has a freezer channel where Houses 2, 3, and 5 have fridges. Treat
Fridge and Freezer as distinct appliance labels. Do not score one as the other.
For direct cross-house comparison, report the five shared labels: WashMach,
Dishwash, Microwave, Toaster, and Kettle. Report Fridge on Houses 2/3/5 and
Freezer on House 6 as house-specific results.

## Audit interpretation

`audit.json` reports source row counts, issue rows, selected-channel null and
nonfinite counts, adjacent duplicate or out-of-order timestamps, raw counts at
the training ON thresholds, and coverage on an epoch-aligned 15-second grid.
Missing-bin counts exclude rows with `Issues == 1`; a listed gap is the
half-open interval between the last occupied bin and the next occupied bin.
`missing_spans_at_least_1h` lists each gap with at least 240 empty 15-second
bins. The interval endpoints are naive timestamps from the REFIT local `Time`
column. `Unix` is not used for model preprocessing.

Gaps are substantial, including long recording breaks. Do not interpolate or
carry values across empty bins. Issue rows are also omitted before resampling.
The audit's ON counts use thresholds from the training pipeline: Fridge and
Freezer 50 W, WashMach 20 W, Dishwash 10 W, Microwave and Toaster 200 W, and
Kettle 1000 W. These counts describe raw samples, before 15-second averaging.

## Preprocessing contract

For each house independently:

1. Drop rows where `Issues == 1`.
2. On Aggregate and mapped appliance channels, clip values above 10,000 W to
   10,000 W and replace values below 5 W with 0 W.
3. Parse `Time`, sort by timestamp, and take the mean of available rows in each
   epoch-aligned 15-second bin. Do not fill bins with no remaining rows.
4. Keep only finite bins. Split into contiguous valid runs, then emit
   non-overlapping 256-step windows wholly inside a run; discard short tails.
   Thus no window spans a recording gap or issue-only interval.
5. Use aggregate power plus deterministic calendar features (minute, hour,
   weekday, month sine/cosine) as inputs. Appliance labels remain in watts.

This mirrors `dataset/training/train_house.py`. The audit counts coverage gaps
after issue removal, before clipping and resampling. Current row-level audit
shows zero null/nonfinite selected values and zero adjacent duplicate or
out-of-order timestamps in all four files; see `audit.json` for exact counts.

## Leakage-safe LOHO evaluation

Run four outer folds, holding out one complete house each time. For fold `h`,
train on the other three houses and evaluate only on `h`; no timestamp, window,
label, or statistic from `h` may affect model fitting, early stopping,
threshold selection, normalization, or model selection. The held-out house is
opened only for final scoring after the fold model and thresholds are frozen.

- Build windows per house before combining them. Keep each full window within
  one house and one contiguous valid run. Never split random windows from the
  same house between training and outer evaluation.
- Fit power scaling and any learned preprocessing using outer-training houses
  only. Calendar features can be calculated from each row's timestamp because
  they are known inputs, not fitted statistics.
- If hyperparameters, ON thresholds, or stopping epochs need selection, split
  only the outer-training houses into grouped inner folds. Keep all windows
  from an inner validation house out of that inner fit. Refit the chosen setup
  on all outer-training houses, then score the held-out house once.
- Train/evaluate shared-label heads on the five appliances available in all
  houses. Fridge can be trained/evaluated only where fridge labels exist;
  Freezer only where its label exists. Do not fabricate a sixth shared class.
- Report per-house, per-appliance metrics first, then macro-average across
  eligible held-out houses so longer recordings do not dominate. Also report
  valid window/sample counts and true ON counts with each metric. Freeze the
  ON thresholds above unless a threshold is selected inside the inner folds.
- Distinguish the LOHO result from temporal in-house testing and from
  source-model transfer. Those answer different questions and must not be
  pooled into the LOHO macro score.

The existing `dataset/training/train_house.py` is a single-house temporal
training pipeline. This protocol defines the outer-fold boundaries for a
multi-house experiment; a multi-house trainer should preserve this boundary
before results are described as LOHO.
