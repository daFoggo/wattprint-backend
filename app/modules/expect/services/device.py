import asyncio
import uuid
from datetime import UTC, date, datetime, time, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings

from .features import (
    FULL_DAY_MIN,
    FULL_HOUR_MIN,
    _hours,
    base_frame,
    excluded_hours,
    feature_frame,
)
from .predict import predict
from .refresh import _midnight, _tz, active_bundle, due, fit_bundle, last_trained, store
from .train import Bundle, eligible

HOLDOUT_DAYS = 21  # 3 weeks: a home with gaps still measures 7+ full days
ROUTINE_WEEKS = 4


def with_level(x: pd.DataFrame, own_daily_level: pd.Series) -> pd.DataFrame:
    """The home's inputs with `base_7d` the device's own recent daily kWh."""
    out = x.copy()
    out["base_7d"] = own_daily_level.reindex(x.index)
    return out


def trusted_device(b: Bundle | None) -> bool:
    """A device model is shown and judged with only when it beat the weekday-hour mean."""
    bt = (b.metrics.get("backtest") if b else None) or {}
    return "mae_model" in bt and bt["mae_model"] < bt["mae_base"]


def method(b: Bundle | None) -> str:
    """What a device's forecast comes from: its model when it beat the weekday-hour mean, else
    that mean ("weekday")."""
    return "model" if trusted_device(b) else "weekday"


def confidence(b: Bundle | None) -> tuple[str, float | None, int]:
    """(high/medium/low, the shown method's daily error over mean daily kWh, days measured):
    the holdout of whichever method is shown; under 7 measured days it is low."""
    bt = (b.metrics.get("backtest") if b else None) or {}
    wape = bt.get("wape_model" if method(b) == "model" else "wape_base")
    days = int(bt.get("days", 0))
    if wape is None or days < 7:
        return "low", wape, days
    if wape <= settings.device_high_wape:
        return "high", wape, days
    return ("medium" if wape <= settings.device_medium_wape else "low"), wape, days


def tail_as_of(x: pd.DataFrame, y: pd.Series, tz: str, cut: pd.Timestamp) -> pd.DataFrame:
    """The holdout's inputs after `cut` with the device's level as the live forecast would know
    it at `cut` (its last 7 full days, held for every later day): the frame's own `base_7d` is
    each day's true trailing level, which a forecast made at `cut` cannot see."""
    known = y[y.index <= cut]
    local = known.index.tz_convert(tz).date
    daily = known.groupby(local).sum().where(known.notna().groupby(local).sum() >= 22)
    return with_level(x[x.index > cut], base_frame(daily, x.index[x.index > cut], tz, cut))


def holdout(x: pd.DataFrame, y: pd.Series, tz: str, days: int = HOLDOUT_DAYS) -> dict:
    """Learn on all but the last `days`, then compare daily kWh with the same weekday-hour mean of
    the 4 weeks before: mean absolute error of both, and how often a day fell in [Σ P10, Σ P90]."""
    cut = y.index[-1] - pd.Timedelta(days=days)
    head = fit_bundle(x[x.index <= cut], y[y.index <= cut], "holdout", tz)
    tail_x, tail_y = tail_as_of(x, y, tz, cut), y[y.index > cut]
    p = predict(head, tail_x)
    past = y[(y.index <= cut) & (y.index > cut - pd.Timedelta(weeks=ROUTINE_WEEKS))]
    mean = past.groupby([past.index.day_of_week, past.index.hour]).mean()
    base = pd.Series(
        [mean.get((t.day_of_week, t.hour), np.nan) for t in tail_y.index], index=tail_y.index
    )
    frame = pd.DataFrame(
        {"y": tail_y, "m": p["p50"], "lo": p["p10"], "hi": p["p90"], "b": base}
    ).dropna()
    d = frame.groupby(frame.index.tz_convert(tz).date).sum()
    d = d[frame.groupby(frame.index.tz_convert(tz).date).size() >= 22]
    if d.empty:
        return {"days": 0}
    mean = float(d["y"].mean())
    mae_model, mae_base = (
        float((d["m"] - d["y"]).abs().mean()),
        float((d["b"] - d["y"]).abs().mean()),
    )
    ratio = (d["y"] / d["b"])[d["b"] > 0]  # the weekday mean's daily misses, for its range
    return {
        "mae_model": mae_model,
        "mae_base": mae_base,
        "wape_model": mae_model / mean if mean > 0 else None,
        "wape_base": mae_base / mean if mean > 0 else None,
        "coverage": float(((d["y"] >= d["lo"]) & (d["y"] <= d["hi"])).mean()),
        "base_q10": float(ratio.quantile(0.1)) if len(ratio) else None,
        "base_q90": float(ratio.quantile(0.9)) if len(ratio) else None,
        "days": int(len(d)),
        "mean_kwh": mean,
    }


async def _series(s: AsyncSession, device_id: uuid.UUID) -> uuid.UUID | None:
    return await s.scalar(
        text(
            "SELECT series_id FROM public.tb_series WHERE device_id = :d AND kind = 'device' "
            "AND metric = 'power_w' LIMIT 1"
        ),
        {"d": device_id},
    )


async def device_actual(
    s: AsyncSession, device_id: uuid.UUID, lo: datetime, hi: datetime
) -> pd.Series:
    """The device's kWh per hour over [lo, hi) from NILM; NaN where under 54 minutes estimated."""
    index = _hours(lo, hi)
    sid = await _series(s, device_id)
    rows = (
        (
            await s.execute(
                text(
                    "SELECT bucket, energy_wh / 1000 AS kwh, covered_minutes AS cov "
                    "FROM public.device_estimate_1h WHERE series_id = :s AND bucket >= :lo "
                    "AND bucket < :hi"
                ),
                {"s": sid, "lo": index[0] if len(index) else lo, "hi": hi},
            )
        ).all()
        if sid
        else []
    )
    got = {pd.Timestamp(r.bucket): float(r.kwh) for r in rows if (r.cov or 0) >= FULL_HOUR_MIN}
    return pd.Series([got.get(t, np.nan) for t in index], index=index, dtype=float)


async def _device_daily(
    s: AsyncSession, device_id: uuid.UUID, lo: datetime, hi: datetime, tz: str
) -> pd.Series:
    sid = await _series(s, device_id)
    rows = (
        (
            await s.execute(
                text(
                    "SELECT bucket, energy_wh / 1000 AS kwh, covered_minutes AS cov "
                    "FROM public.device_estimate_1d WHERE series_id = :s AND bucket >= :lo "
                    "AND bucket < :hi"
                ),
                {"s": sid, "lo": lo, "hi": hi},
            )
        ).all()
        if sid
        else []
    )
    return pd.Series(
        {
            pd.Timestamp(r.bucket).tz_convert(tz).date(): (
                float(r.kwh) if (r.cov or 0) >= FULL_DAY_MIN else np.nan
            )
            for r in rows
        },
        dtype=float,
    )


async def device_level(
    s: AsyncSession, home_id: uuid.UUID, device_id: uuid.UUID, day: date
) -> float:
    """The device's `base_7d` as known the morning of `day`: its mean kWh over the full local days
    of the 7 before (NaN without one)."""
    tz = await _tz(s, home_id)
    at = pd.Timestamp(datetime.combine(day, time()), tz=tz)
    daily = await _device_daily(
        s, device_id, (at - pd.Timedelta(days=9)).tz_convert("UTC"), at.tz_convert("UTC"), tz
    )
    return float(base_frame(daily, pd.DatetimeIndex([at]), tz, at).iloc[0])


async def device_frame(
    s: AsyncSession,
    home_id: uuid.UUID,
    device_id: uuid.UUID,
    lo: datetime,
    hi: datetime,
    now: datetime,
    home_x: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """The home's context features (`home_x` when the caller already has them for [lo, hi)), with
    the device's own 7-day level as `base_7d`."""
    x = home_x if home_x is not None else await feature_frame(s, home_id, lo, hi, now)
    tz = await _tz(s, home_id)
    now_ = pd.Timestamp(now).tz_convert("UTC")
    daily = await _device_daily(
        s, device_id, x.index[0] - pd.Timedelta(days=9), now_ + pd.Timedelta(days=1), tz
    )
    return with_level(x, base_frame(daily, x.index, tz, now_))


async def train_device(
    s: AsyncSession, home_id: uuid.UUID, device_id: uuid.UUID, now: datetime, force: bool = False
) -> str | None:
    """Learn one device's model (weekly, like the home's) from its NILM history before today,
    with its holdout check against the weekday-hour mean in metrics.backtest."""
    if not force and not due(await last_trained(s, home_id, device_id), now):
        return None
    tz = await _tz(s, home_id)
    hi = _midnight(now, tz)
    lo = hi - timedelta(days=settings.expect_history_days)
    y = await device_actual(s, device_id, lo, hi)
    y[(await excluded_hours(s, home_id, lo, hi)).reindex(y.index, fill_value=False)] = np.nan
    if not eligible(y, tz):
        return None
    x = await device_frame(s, home_id, device_id, lo, hi, now)
    version = f"dev-v2-{now.astimezone(UTC):%Y%m%d%H%M%S}"  # v2: the centre is the mean
    bundle = await asyncio.to_thread(fit_bundle, x, y, version, tz)
    bundle.metrics["backtest"] = await asyncio.to_thread(holdout, x, y, tz)
    await store(s, home_id, device_id, bundle, now)
    return version


async def device_band(
    s: AsyncSession,
    home_id: uuid.UUID,
    device_id: uuid.UUID,
    lo: datetime,
    hi: datetime,
    now: datetime,
) -> pd.DataFrame | None:
    """The trusted device model's hourly quantiles (and contributions) over [lo, hi); None
    without one."""
    b = await active_bundle(s, home_id, device_id)
    if not trusted_device(b):
        return None
    return predict(b, await device_frame(s, home_id, device_id, lo, hi, now))


# What a device's forecast is explained by, against its usual: weather split into its parts (each
# input's own TreeSHAP share), the other groups whole (trend also holds the level's move).
WEATHER_PARTS = {
    "temperature": ("temp_c", "temp_24h", "temp_72h", "apparent_c"),
    "humidity": ("humidity_pct",),
    "sun": ("cloud_pct", "radiation_wm2", "is_day"),
    "rain": ("precip_mm",),
}
WHOLE = {"calendar": "c_calendar", "occupancy": "c_occupancy", "trend": "c_trend"}
FACTOR_MIN_SHARE = 0.05  # a factor worth a line moves the day by 5 % of the usual
MAX_FACTORS = 3
# Factors are told apart only when the model's own past is within 15 % of the measured usual: a
# device it misses (short bursts summed as hourly medians) gets no made-up reasons.
MODEL_FIT = 0.15
# The trend's line names the weather when the last week was this much colder or warmer than the
# past 28 days: a model that learns from the recent level puts a cold week in the trend.
TREND_TEMP_C = 1.0
# ...and only for a device whose own temperature shares follow the temperature (|r| ≥ 0.3), in the
# direction its level moved: no weather named for a TV, nor "less after a colder week" for a heater.
TEMP_RESPONSE_R = 0.3


def _per_day(s: pd.Series, tz: str, full: int = 22) -> pd.Series:
    """Daily sums of an hourly series over local days with at least `full` known hours."""
    local = s.index.tz_convert(tz).date
    sums = s.groupby(local).sum()
    return sums[s.notna().groupby(local).sum() >= full]


def explain_outlook(
    future_p: pd.DataFrame,
    future_x: pd.DataFrame,
    past_p: pd.DataFrame,
    past_x: pd.DataFrame,
    past_actual: pd.Series,
    tz: str,
) -> dict:
    """The forecast against the device's usual, kWh a day: usual = its measured daily mean over
    the past days, forecast = the P50's daily mean over the days ahead. Each factor = its share
    ahead minus its share over the past, both at the past's mean level (TreeSHAP in model units);
    trend = the rest of the model's change (the level's move with it); "other" = the model's own
    past against the measured usual, so `all` + `other` add up to forecast − usual. `factors`: at
    most 3 that move a day by 5 % of the usual, biggest first, with their evidence (the input's
    mean ahead `now` against the past `before`); none unless `explainable` (the model's past
    within 15 % of the usual)."""
    usual = float(_per_day(past_actual, tz).mean())
    forecast = float(_per_day(future_p["p50"], tz).mean())

    def mean(x: pd.DataFrame, col: str) -> float | None:
        return float(x[col].mean()) if col in x and x[col].notna().any() else None

    def days_off_per_week(x: pd.DataFrame) -> float:
        local = x.index.tz_convert(tz)
        day = pd.DataFrame({"off": (x["holiday"] > 0) | (local.day_of_week >= 5)}, index=local)
        off = day.groupby(local.date)["off"].max()
        return float(off.sum() * 7 / len(off)) if len(off) else 0.0

    def rain(x: pd.DataFrame) -> float | None:
        return float(_per_day(x["precip_mm"], tz).mean()) if "precip_mm" in x else None

    evidence = {
        "temperature": (mean(future_x, "temp_c"), mean(past_x, "temp_c")),
        "humidity": (mean(future_x, "humidity_pct"), mean(past_x, "humidity_pct")),
        "sun": (mean(future_x, "radiation_wm2"), mean(past_x, "radiation_wm2")),
        "rain": (rain(future_x), rain(past_x)),
        "calendar": (days_off_per_week(future_x), days_off_per_week(past_x)),
        "occupancy": (mean(future_x, "presence"), mean(past_x, "presence")),
        "trend": (mean(future_x, "base_7d"), usual),
    }
    measured = _per_day(past_actual, tz).index  # the days the usual counts
    model_past = float(_per_day(past_p["p50"], tz).reindex(measured).mean())
    level = float(past_p["scale"].mean()) if "scale" in past_p else 1.0

    def at_level(p: pd.DataFrame, cols: list[str]) -> float:
        """A factor's kWh a day at the past's mean level: its shares in model units (each hour's
        own level taken out), so a move in the level is the trend's, not the weather's."""
        cols = [c for c in cols if c in p]
        if not cols:
            return 0.0
        unit = p[cols].sum(axis=1) / (p["scale"] if "scale" in p else 1.0)
        return float(unit.mean()) * 24 * level

    deltas = {
        k: at_level(future_p, [f"f_{c}" for c in cols]) - at_level(past_p, [f"f_{c}" for c in cols])
        for k, cols in WEATHER_PARTS.items()
    } | {
        k: at_level(future_p, [c]) - at_level(past_p, [c]) for k, c in WHOLE.items() if k != "trend"
    }
    deltas["trend"] = forecast - model_past - sum(deltas.values())  # the level and what it learnt
    recent = mean(past_x[past_x.index > past_x.index.max() - pd.Timedelta(days=7)], "temp_c")
    usual_temp = mean(past_x, "temp_c")
    temp_cols = [f"f_{c}" for c in WEATHER_PARTS["temperature"] if f"f_{c}" in past_p]
    response = None  # how the device's temperature shares follow the temperature: r
    if temp_cols and "temp_c" in past_x:
        shares = past_p[temp_cols].sum(axis=1) / (past_p["scale"] if "scale" in past_p else 1.0)
        if shares.std() > 0 and past_x["temp_c"].std() > 0:
            response = float(shares.corr(past_x["temp_c"]))
    cause = (
        recent is not None
        and usual_temp is not None
        and abs(recent - usual_temp) >= TREND_TEMP_C
        and response is not None
        and abs(response) >= TEMP_RESPONSE_R
        and response * (recent - usual_temp) * deltas["trend"] > 0  # the move fits the weather
    )
    lines = [
        {
            "key": k,
            "kwh_day": d,
            "now": evidence[k][0],
            "before": evidence[k][1],
            "recent_temp": recent if k == "trend" and cause else None,
            "usual_temp": usual_temp if k == "trend" and cause else None,
        }
        for k, d in sorted(deltas.items(), key=lambda kv: -abs(kv[1]))
    ]
    bar = FACTOR_MIN_SHARE * usual
    explainable = usual > 0 and abs(model_past - usual) <= MODEL_FIT * usual
    return {
        "usual": usual,
        "forecast": forecast,
        "explainable": explainable,
        "factors": [f for f in lines if abs(f["kwh_day"]) >= bar][:MAX_FACTORS]
        if explainable
        else [],
        "all": lines,
        "other": model_past - usual,  # what the model's own past misses of the measured usual
    }


def weekday_outlook(past: pd.Series, index: pd.DatetimeIndex, q10, q90) -> pd.DataFrame:
    """Hourly kWh over `index` as the same weekday-hour mean of `past` (the 4 weeks before), with
    P10/P90 its holdout's daily misses (q10/q90 of actual over this mean); no contributions."""
    mean = past.groupby([past.index.day_of_week, past.index.hour]).mean()
    p50 = pd.Series([mean.get((t.day_of_week, t.hour), np.nan) for t in index], index=index)
    return pd.DataFrame(
        {
            "p10": p50 * q10 if q10 is not None else np.nan,
            "p50": p50,
            "p90": p50 * q90 if q90 is not None else np.nan,
        }
    )


EXPLAIN_DAYS = 7  # the whole days ahead the explanation is about (from tomorrow)
PAST_DAYS = 28  # the device's usual: its measured daily mean over these days


async def device_outlook(
    s: AsyncSession,
    home_id: uuid.UUID,
    device_id: uuid.UUID,
    now: datetime,
    hi: datetime,
    home_x: pd.DataFrame | None = None,
) -> dict | None:
    """A device's expected kWh per local day (P10/P50/P90) from the running hour to `hi`, and at
    least through the 7 whole days ahead; from its model when it beat the weekday-hour mean in
    its holdout, else from that mean; with the certainty of the method shown and `explain`: the
    7 whole days ahead against its usual (explain_outlook; the weekday mean has no factors).
    None without a model. `home_x`: the home's feature_frame over [28 days before today, hi)."""
    b = await active_bundle(s, home_id, device_id)
    if b is None:
        return None
    tz = await _tz(s, home_id)
    lo = pd.Timestamp(now).tz_convert("UTC").floor("h")
    today = pd.Timestamp(_midnight(now, tz))
    ahead_lo, ahead_hi = today + pd.Timedelta(days=1), today + pd.Timedelta(days=1 + EXPLAIN_DAYS)
    hi = max(pd.Timestamp(hi), ahead_hi)
    past_lo = today - pd.Timedelta(days=PAST_DAYS)
    actual = await device_actual(s, device_id, past_lo, today)
    shown = method(b)
    if shown == "model":
        x = await device_frame(s, home_id, device_id, past_lo, hi, now, home_x)
        # LightGBM with TreeSHAP, off the event loop
        p = await asyncio.to_thread(predict, b, x, True)
        hourly = p.loc[p.index >= lo, ["p10", "p50", "p90"]]
        ahead = (p.index >= ahead_lo) & (p.index < ahead_hi)
        past = p.index < today
        explain = explain_outlook(p[ahead], x[ahead], p[past], x[past], actual, tz)
    else:
        bt = b.metrics.get("backtest") or {}
        hourly = weekday_outlook(
            actual.dropna(), _hours(lo, hi), bt.get("base_q10"), bt.get("base_q90")
        )
        usual = float(_per_day(actual, tz).mean())
        mid = hourly["p50"][(hourly.index >= ahead_lo) & (hourly.index < ahead_hi)]
        forecast = float(_per_day(mid, tz).mean())
        explain = {"usual": usual, "forecast": forecast, "explainable": False}
        explain |= {"factors": [], "all": []}
        explain["other"] = forecast - usual
    if not all(np.isfinite([explain["usual"], explain["forecast"]])):
        explain = None  # no full day measured, or none ahead: nothing to explain against
    if (
        len(hourly) and hourly.index[0] == lo
    ):  # the running hour counts by its rest, as the bill does
        hourly = hourly.copy()
        hourly.iloc[0] *= 1 - (pd.Timestamp(now) - lo).total_seconds() / 3600
    daily = hourly.groupby(hourly.index.tz_convert(tz).date).sum(min_count=1)
    level, wape, days = confidence(b)
    return {
        "method": shown,
        "confidence": level,
        "wape": wape,
        "backtest_days": days,
        "days": [
            {"date": d, **{k: (None if pd.isna(v) else float(v)) for k, v in r.items()}}
            for d, r in daily.iterrows()
        ],
        "explain": explain,
    }
