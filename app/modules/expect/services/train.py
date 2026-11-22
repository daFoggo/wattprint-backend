from dataclasses import dataclass, field
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd

QUANTILES = (0.05, 0.1, 0.5, 0.9, 0.95)
PARAMS = {
    "objective": "quantile",
    "num_leaves": 31,
    "min_data_in_leaf": 20,
    "learning_rate": 0.05,
    "feature_fraction": 0.9,
    "verbose": -1,
    "num_threads": 2,  # the insight worker shares the host with the API
}
ROUNDS = 300
MIN_DAYS = 28
FULL_DAY_HOURS = 22  # 90 % of a day's hours
RESIDUAL_DAYS = 60
MIN_KNOWN = 0.5  # share of training hours a feature must be known for


@dataclass
class Bundle:
    version: str
    features: tuple[str, ...]
    boosters: dict[float, lgb.Booster]
    residuals: list[float]  # daily kWh errors of the P50 on days it did not learn from
    # Conformal widening (CQR) per band, kWh: "80" moves P10/P90 out, "90" moves P05/P95 out, so
    # the bands cover 80 % and 90 % of the hours the model did not learn from.
    widen: dict[str, float] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)


def full_days(y: pd.Series, tz: str) -> pd.Series:
    """Per local day: True when at least 22 of its hours are known."""
    known = y.notna().groupby(y.index.tz_convert(tz).date).sum()
    return known >= FULL_DAY_HOURS


def eligible(y: pd.Series, tz: str) -> bool:
    return int(full_days(y, tz).sum()) >= MIN_DAYS


def _boost(x: pd.DataFrame, y: pd.Series, q: float, seed: int) -> lgb.Booster:
    data = lgb.Dataset(x, label=y, free_raw_data=False)
    return lgb.train({**PARAMS, "alpha": q, "seed": seed}, data, num_boost_round=ROUNDS)


def level(x: pd.DataFrame, ref_h: float | None = None) -> pd.Series:
    """The home's recent hourly level (kWh): its last 7 days' mean per hour, else `ref_h`."""
    base = x["base_7d"] / 24 if "base_7d" in x else pd.Series(np.nan, index=x.index)
    return base.where(base > 0, ref_h if ref_h is not None else np.nan)


def fit(
    x: pd.DataFrame, y: pd.Series, *, version: str, tz: str = "Asia/Ho_Chi_Minh", seed: int = 7
) -> Bundle:
    """Boosters learn each hour's kWh as a ratio of the home's recent level, so a forecast follows
    a new level (as the weekday average does) while weather, calendar and routine shape it. One
    booster per quantile on every known hour; the band is widened (CQR) and the P50's daily kWh
    errors kept from the last fifth of the hours, learnt on the first four fifths."""
    known = y.notna() & x.notna().any(axis=1) & (level(x) > 0)
    x, y = x[known], y[known]
    # A feature unknown for most hours (presence before NILM had analysed them) would be learnt
    # as "missing" and then read with values: leave it out until its history fills in.
    x = x.loc[:, x.notna().mean() >= MIN_KNOWN]
    base = level(x)
    r = y / base
    boosters = {q: _boost(x, r, q, seed) for q in QUANTILES}
    cut = int(len(x) * 0.8)
    head = {q: _boost(x.iloc[:cut], r.iloc[:cut], q, seed) for q in QUANTILES}
    rt, xt, bt = r.iloc[cut:].to_numpy(), x.iloc[cut:], base.iloc[cut:].to_numpy()
    pred = {q: m.predict(xt) for q, m in head.items()}
    widen = {}
    for band, (lo, hi, cover) in {"80": (0.1, 0.9, 0.8), "90": (0.05, 0.95, 0.9)}.items():
        score = np.maximum(pred[lo] - rt, rt - pred[hi])
        q = min(1.0, cover * (1 + 1 / len(score)))
        widen[band] = max(0.0, float(np.quantile(score, q)))
    tail = pd.DataFrame({"y": rt * bt, "p": pred[0.5] * bt}, index=x.index[cut:])
    day = tail.index.tz_convert(tz).date
    sums = tail.groupby(day).agg(y=("y", "sum"), p=("p", "sum"), n=("y", "size"))
    sums = sums[sums["n"] >= FULL_DAY_HOURS]
    residuals = (sums["y"] - sums["p"]).tolist()[-RESIDUAL_DAYS:]
    return Bundle(
        version, tuple(x.columns), boosters, residuals, widen, {"ref_h": float(base.median())}
    )


def to_row(b: Bundle) -> dict[str, Any]:
    return {
        "version": b.version,
        "features": list(b.features),
        "boosters": {str(q): m.model_to_string() for q, m in b.boosters.items()},
        "residuals": [float(r) for r in b.residuals],
        "widen": b.widen,
        "metrics": b.metrics,
    }


def from_row(row: Any) -> Bundle:
    get = row.get if isinstance(row, dict) else lambda k: getattr(row, k)
    return Bundle(
        version=get("version"),
        features=tuple(get("features")),
        boosters={float(q): lgb.Booster(model_str=s) for q, s in get("boosters").items()},
        residuals=list(get("residuals") or []),
        widen=dict(get("widen") or {}),
        metrics=dict(get("metrics") or {}),
    )
