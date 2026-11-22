"""Chunked REFIT channel and time audit; run from any working directory."""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
CHANNELS = {
    2: {'Fridge': 'Appliance1', 'WashMach': 'Appliance2', 'Dishwash': 'Appliance3', 'Microwave': 'Appliance5', 'Toaster': 'Appliance6', 'Kettle': 'Appliance8'},
    3: {'Fridge': 'Appliance2', 'WashMach': 'Appliance6', 'Dishwash': 'Appliance5', 'Microwave': 'Appliance8', 'Toaster': 'Appliance1', 'Kettle': 'Appliance9'},
    5: {'Fridge': 'Appliance1', 'WashMach': 'Appliance3', 'Dishwash': 'Appliance4', 'Microwave': 'Appliance7', 'Toaster': 'Appliance9', 'Kettle': 'Appliance8'},
    6: {'Freezer': 'Appliance1', 'WashMach': 'Appliance2', 'Dishwash': 'Appliance3', 'Microwave': 'Appliance6', 'Toaster': 'Appliance8', 'Kettle': 'Appliance7'},
}
THRESHOLDS = {'Fridge':50, 'Freezer':50, 'WashMach':20, 'Dishwash':10, 'Microwave':200, 'Toaster':200, 'Kettle':1000}

def audit_house(house: int) -> dict:
    mapping = CHANNELS[house]
    cols = ['Time', 'Aggregate', *mapping.values(), 'Issues']
    rows = kept = issues = nonfinite = duplicate = invalid_time = out_of_order = 0
    first = last = prev = None
    bins = []
    positives = {name: 0 for name in mapping}
    raw_nan = {c: 0 for c in cols[1:]}
    for chunk in pd.read_csv(ROOT / f'CLEAN_House{house}.csv', usecols=cols, chunksize=250_000):
        rows += len(chunk)
        dt = pd.to_datetime(chunk['Time'], errors='coerce')
        if first is None: first = dt.min()
        last = dt.max()
        invalid_time += int(dt.isna().sum())
        ns = dt.dropna().to_numpy(dtype='datetime64[ns]').astype('int64')
        if len(ns):
            duplicate += int(np.sum(np.diff(ns) == 0))
            out_of_order += int(np.sum(np.diff(ns) < 0))
            if prev is not None:
                duplicate += int(ns[0] == prev)
                out_of_order += int(ns[0] < prev)
            prev = ns[-1]
        issues += int((chunk['Issues'] == 1).sum())
        for c in raw_nan: raw_nan[c] += int(chunk[c].isna().sum())
        good = chunk['Issues'] != 1
        kept += int(good.sum())
        values = chunk.loc[good, ['Aggregate', *mapping.values()]].to_numpy(dtype='float64')
        nonfinite += int((~np.isfinite(values).all(axis=1)).sum())
        for name, col in mapping.items(): positives[name] += int((chunk.loc[good, col] >= THRESHOLDS[name]).sum())
        # Unique 15-second bins after dropping issue rows: compact, exact gap count.
        valid_ts = good & dt.notna()
        ts = dt.loc[valid_ts].to_numpy(dtype='datetime64[s]').astype('int64')
        bins.append(np.unique(ts // 15))
    occupied = np.unique(np.concatenate(bins))
    diffs = np.diff(occupied)
    gap_bins = int(np.maximum(diffs - 1, 0).sum())
    gaps = diffs[diffs > 1] - 1
    long_gaps = []
    for i in np.flatnonzero(diffs - 1 >= 240):
        missing = int(diffs[i] - 1)
        start = pd.to_datetime(int(occupied[i] + 1) * 15, unit='s')
        end = pd.to_datetime(int(occupied[i + 1]) * 15, unit='s')
        long_gaps.append({'start_inclusive': str(start), 'end_exclusive': str(end),
                          'missing_15s_bins': missing, 'duration_seconds': missing * 15})
    return dict(house=house, raw_rows=rows, rows_after_issues=kept, issues_rows=issues,
        raw_nonfinite_selected_rows_after_issues=nonfinite, duplicate_adjacent_timestamps=duplicate,
        invalid_timestamps=invalid_time, out_of_order_adjacent_timestamps=out_of_order,
        first_time=str(first), last_time=str(last), occupied_15s_bins=int(len(occupied)),
        missing_15s_bins_between_first_last=gap_bins, gap_count=int(len(gaps)),
        largest_gap_15s_bins=int(gaps.max()) if len(gaps) else 0,
        missing_spans_at_least_1h=long_gaps,
        raw_nan_by_column=raw_nan, raw_positive_counts_after_issues=positives,
        channels=mapping, on_threshold_w={k:THRESHOLDS[k] for k in mapping})

if __name__ == '__main__':
    result = {'audit_version': '1.1.0', 'sample_seconds': 15,
              'gap_definition': 'missing epoch-aligned 15-second bins after excluding Issues=1 rows; spans list only gaps of at least 240 missing bins (1 hour)',
              'houses': [audit_house(h) for h in (2,3,5,6)]}
    path = Path(__file__).with_name('audit.json')
    path.write_text(json.dumps(result, indent=2) + '\n')
    print(path)
