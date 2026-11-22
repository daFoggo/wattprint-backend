import numpy as np
import pandas as pd
import pytest

from app.modules.expect.services.features import FEATURES, GROUPS
from app.modules.expect.services.predict import predict
from app.modules.expect.services.train import QUANTILES, eligible, fit, from_row, to_row


def synthetic(days: int, seed: int = 1) -> tuple[pd.DataFrame, pd.Series]:
    """Hourly frame where usage rises in the cold and in the evening, plus noise."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2026-01-01", periods=days * 24, freq="h", tz="UTC")
    hour = idx.hour.to_numpy()
    day = np.arange(len(idx)) // 24
    temp = 10 + 8 * np.sin(day / 9.0) + rng.normal(0, 1, len(idx))
    x = pd.DataFrame(0.0, index=idx, columns=list(FEATURES))
    x["temp_c"] = temp
    x["temp_24h"] = pd.Series(temp, index=idx).rolling(24, min_periods=1).mean()
    x["temp_72h"] = pd.Series(temp, index=idx).rolling(72, min_periods=1).mean()
    x["hour"] = hour
    x["weekday"] = idx.day_of_week
    x["presence"] = ((hour >= 18) & (hour < 22)).astype(float)
    x["base_7d"] = 30.0
    y = 1 + 0.1 * np.maximum(0, 16 - temp) + 0.5 * ((hour >= 18) & (hour < 22))
    y = pd.Series(y + rng.normal(0, 0.1, len(idx)), index=idx)
    return x, y


@pytest.fixture(scope="module")
def model():
    x, y = synthetic(60)
    return (
        fit(x.iloc[: 50 * 24], y.iloc[: 50 * 24], version="ctx-v1-test"),
        x.iloc[50 * 24 :],
        y.iloc[50 * 24 :],
    )


def test_quantiles_ordered_and_cover(model):
    b, x, y = model
    p = predict(b, x)
    assert (p["p05"] <= p["p10"]).all() and (p["p10"] <= p["p50"]).all()
    assert (p["p50"] <= p["p90"]).all() and (p["p90"] <= p["p95"]).all()
    inside = ((y >= p["p10"]) & (y <= p["p90"])).mean()
    assert 0.65 <= inside <= 0.95


def test_contributions_add_up(model):
    b, x, _ = model
    p = predict(b, x)
    total = p["c_base"] + sum(p[f"c_{g}"] for g in GROUPS)
    assert np.allclose(total, p["p50_raw"], rtol=0.01, atol=1e-6)


def test_cold_hours_owe_their_rise_to_weather(model):
    b, x, _ = model
    cold, warm = x.copy(), x.copy()
    for col in ("temp_c", "temp_24h", "temp_72h"):
        cold[col], warm[col] = 4.0, 18.0
    assert predict(b, cold)["c_weather"].mean() > predict(b, warm)["c_weather"].mean() + 0.5


def test_bundle_survives_storage(model):
    b, x, _ = model
    again = from_row(to_row(b))
    assert again.version == b.version and again.residuals == pytest.approx(b.residuals)
    assert np.allclose(predict(again, x)["p50"], predict(b, x)["p50"])
    assert set(b.boosters) == set(QUANTILES)


def test_train_needs_28_full_days():
    _, y = synthetic(40)
    tz = "Asia/Ho_Chi_Minh"
    assert eligible(y.iloc[: 27 * 24 + 12], tz) is False
    assert eligible(y.iloc[: 29 * 24 + 12], tz) is True
    gappy = y.iloc[: 35 * 24].copy()
    gappy.iloc[::5] = np.nan  # every fifth hour missing: no full day left
    assert eligible(gappy, tz) is False


def test_fit_leaves_out_features_missing_for_most_hours():
    x, y = synthetic(40)
    x["presence"] = np.nan
    x.iloc[-5 * 24 :, x.columns.get_loc("presence")] = 1.0  # known only for the last 5 days
    b = fit(x, y, version="t")
    assert "presence" not in b.features and "temp_c" in b.features
    p = predict(b, x.iloc[-24:])
    assert (p["c_occupancy"] == 0).all()


def test_a_new_usage_level_is_followed_not_capped():
    x, y = synthetic(60)
    x["base_7d"] = 24 * y.rolling(24 * 7, min_periods=24).mean().shift(24).bfill()
    b = fit(x.iloc[: 50 * 24], y.iloc[: 50 * 24], version="t")
    later = x.iloc[50 * 24 :].copy()
    later["base_7d"] *= 2  # the home now uses twice as much
    low, high = predict(b, x.iloc[50 * 24 :])["p50"].sum(), predict(b, later)["p50"].sum()
    assert high == pytest.approx(2 * low, rel=0.15)


def test_a_level_change_is_owed_to_the_trend():
    x, y = synthetic(60)
    x["base_7d"] = 24 * y.rolling(24 * 7, min_periods=24).mean().shift(24).bfill()
    b = fit(x.iloc[: 50 * 24], y.iloc[: 50 * 24], version="t")
    now, later = x.iloc[50 * 24 :].copy(), x.iloc[50 * 24 :].copy()
    later["base_7d"] *= 1.5
    gap = predict(b, later)["c_trend"].sum() - predict(b, now)["c_trend"].sum()
    rise = predict(b, later)["p50_raw"].sum() - predict(b, now)["p50_raw"].sum()
    assert gap == pytest.approx(rise, rel=0.35) and rise > 0


def test_a_model_is_relearnt_weekly_not_daily():
    from datetime import UTC, datetime, timedelta

    from app.modules.expect.services.refresh import due

    now = datetime(2026, 11, 22, tzinfo=UTC)
    assert due(None, now)
    assert not due(now - timedelta(days=6), now)
    assert due(now - timedelta(days=7), now)


async def test_training_twice_in_a_minute_keeps_a_model_active(monkeypatch):
    from datetime import UTC, datetime

    from sqlalchemy import text

    from app.database import SessionLocal
    from app.modules.expect.services import refresh

    x, y = synthetic(35)

    async def frame(*a, **k):
        return x

    async def actual(*a, **k):
        return y.copy()

    async def none(*a, **k):
        return y.astype(bool) & False

    monkeypatch.setattr(refresh, "feature_frame", frame)
    monkeypatch.setattr(refresh, "hourly_actual", actual)
    monkeypatch.setattr(refresh, "excluded_hours", none)
    async with SessionLocal() as s, s.begin():
        hid = await s.scalar(text("INSERT INTO public.tb_home (name) VALUES ('m') RETURNING id"))
    now = datetime(2026, 11, 22, 3, 0, 5, tzinfo=UTC)
    for _ in range(2):
        async with SessionLocal() as s, s.begin():
            await refresh.train_home(s, hid, now, force=True)
    async with SessionLocal() as s, s.begin():
        n = await s.scalar(
            text("SELECT count(*) FROM public.tb_expect_model WHERE home_id = :h AND active"),
            {"h": hid},
        )
        await s.execute(text("DELETE FROM public.tb_home WHERE id = :h"), {"h": hid})
    assert n == 1
