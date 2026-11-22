import numpy as np
import pandas as pd

from .features import GROUPS
from .train import QUANTILES, Bundle, level

COLUMN = {q: f"p{round(q * 100):02d}" for q in QUANTILES}  # 0.05 -> p05, 0.5 -> p50


def predict(b: Bundle, x: pd.DataFrame) -> pd.DataFrame:
    """kWh quantiles per hour (sorted so they never cross, never below 0) and the P50's TreeSHAP
    contributions summed per factor group, in kWh; c_base + the c_<group> add up to p50_raw. A
    ratio model (metrics.ref_h) is scaled by the home's recent level, and a level away from the
    one it learnt on is owed to the trend."""
    ref_h = b.metrics.get("ref_h")
    scale = level(x, ref_h).to_numpy() if ref_h is not None else np.ones(len(x))
    x = x[list(b.features)]
    raw = np.column_stack([b.boosters[q].predict(x) for q in QUANTILES])
    shift = {
        0.05: -b.widen.get("90", 0),
        0.1: -b.widen.get("80", 0),
        0.5: 0,
        0.9: b.widen.get("80", 0),
        0.95: b.widen.get("90", 0),
    }
    raw_q = (raw + np.array([shift[q] for q in QUANTILES])) * scale[:, None]
    raw = raw * scale[:, None]
    out = pd.DataFrame(
        np.clip(np.sort(raw_q, axis=1), 0, None),
        index=x.index,
        columns=[COLUMN[q] for q in QUANTILES],
    )
    out["p50_raw"] = raw[:, QUANTILES.index(0.5)]
    contrib = b.boosters[0.5].predict(x, pred_contrib=True)
    names = list(b.features)
    for g, cols in GROUPS.items():
        out[f"c_{g}"] = contrib[:, [names.index(c) for c in cols if c in names]].sum(axis=1) * scale
    bias = contrib[:, -1]
    ref = ref_h if ref_h is not None else 1.0
    out["c_base"] = bias * ref
    out["c_trend"] += bias * (scale - ref)  # the level moved from the one learnt on
    return out
