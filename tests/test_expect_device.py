from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import text

from app.database import SessionLocal
from app.modules.expect.services import refresh
from app.modules.expect.services.device import holdout, trusted_device, with_level
from tests.test_expect_model import synthetic


def test_device_frame_uses_the_devices_own_level():
    idx = pd.date_range("2026-11-01", periods=48, freq="h", tz="UTC")
    x = pd.DataFrame({"base_7d": 30.0, "hour": idx.hour}, index=idx)
    own = pd.Series(2.4, index=idx)
    got = with_level(x, own)
    assert (got["base_7d"] == 2.4).all() and (got["hour"] == x["hour"]).all()


def test_device_backtest_against_the_weekday_hour_mean():
    x, y = synthetic(60)
    m = holdout(x, y, "Asia/Ho_Chi_Minh", days=14)
    assert m["days"] >= 12  # the full local days of a UTC holdout
    assert m["mae_model"] > 0 and m["mae_base"] > 0
    assert 0 <= m["coverage"] <= 1
    assert trusted_device(type("B", (), {"metrics": {"backtest": m}})()) == (
        m["mae_model"] < m["mae_base"]
    )
    assert not trusted_device(type("B", (), {"metrics": {}})())


async def test_a_device_model_and_the_home_model_live_side_by_side(monkeypatch):
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
        hid = await s.scalar(text("INSERT INTO public.tb_home (name) VALUES ('d') RETURNING id"))
        did = await s.scalar(
            text(
                "INSERT INTO public.tb_device (home_id, device_type_code, name, origin) "
                "VALUES (:h, 'kettle', 'Kettle', 'nilm') RETURNING id"
            ),
            {"h": hid},
        )
    now = datetime(2026, 11, 22, 3, tzinfo=UTC)
    async with SessionLocal() as s, s.begin():
        await refresh.store(s, hid, did, refresh.fit_bundle(x, y, "dev", "Asia/Ho_Chi_Minh"), now)
    async with SessionLocal() as s, s.begin():
        await refresh.train_home(s, hid, now, force=True)
    async with SessionLocal() as s, s.begin():
        home = await refresh.active_bundle(s, hid)
        device = await refresh.active_bundle(s, hid, did)
        await s.execute(text("DELETE FROM public.tb_home WHERE id = :h"), {"h": hid})
    assert home is not None and device is not None and home.version != device.version


@pytest.fixture(autouse=True)
def _quiet():
    np.seterr(all="ignore")


async def test_demo_events_are_kept_out_of_a_device_model(monkeypatch):
    from app.modules.expect.services import device as dev

    x, y = synthetic(35)

    async def actual(*a, **k):
        return y.copy()

    async def everything(s, h, lo, hi):
        return y.astype(bool) | True  # every hour inside a demo event

    async def tz(*a, **k):
        return "Asia/Ho_Chi_Minh"

    async def never(*a, **k):
        return None

    monkeypatch.setattr(dev, "device_actual", actual)
    monkeypatch.setattr(dev, "excluded_hours", everything)
    monkeypatch.setattr(dev, "_tz", tz)
    monkeypatch.setattr(dev, "last_trained", never)
    assert await dev.train_device(None, None, None, datetime(2026, 11, 22, tzinfo=UTC)) is None


def _bundle(**bt):
    return type("B", (), {"metrics": {"backtest": bt}})()


def test_certainty_is_the_error_of_the_method_shown():
    from app.modules.expect.services.device import confidence, method

    beats = _bundle(mae_model=0.1, mae_base=0.2, wape_model=0.2, wape_base=0.4, days=14)
    loses = _bundle(mae_model=0.3, mae_base=0.2, wape_model=0.6, wape_base=0.4, days=14)
    assert (method(beats), confidence(beats)[0]) == ("model", "high")  # its own 20 %
    assert (method(loses), confidence(loses)[0]) == ("weekday", "medium")  # the mean's 40 %
    assert confidence(_bundle(mae_model=0.1, mae_base=0.2, wape_model=0.1, days=5))[0] == "low"
    assert confidence(None) == ("low", None, 0)


def test_the_weekday_outlook_is_the_same_hour_mean_with_its_misses():
    from app.modules.expect.services.device import weekday_outlook

    past_idx = pd.date_range("2026-10-26", periods=28 * 24, freq="h", tz="UTC")
    past = pd.Series(np.where(past_idx.hour == 7, 0.4, 0.0), index=past_idx)
    nxt = pd.date_range("2026-11-23", periods=24, freq="h", tz="UTC")
    got = weekday_outlook(past, nxt, 0.5, 1.5)
    assert got["p50"].sum() == pytest.approx(0.4)
    assert (got["p10"].sum(), got["p90"].sum()) == (pytest.approx(0.2), pytest.approx(0.6))


def test_the_holdout_forecasts_with_the_level_known_at_its_start():
    from app.modules.expect.services.device import tail_as_of

    x, y = synthetic(30)
    y.iloc[-7 * 24 :] *= 3  # the device's use triples in the last week
    x["base_7d"] = 99.0  # whatever the frame held: the true trailing level, in training
    cut = y.index[-1] - pd.Timedelta(days=14)
    tail = tail_as_of(x, y, "UTC", cut)
    before = y[(y.index > cut - pd.Timedelta(days=7)) & (y.index <= cut)]
    days = before.groupby(before.index.date).sum()
    assert (tail.index > cut).all() and len(tail) == 14 * 24
    assert tail["base_7d"].nunique() == 1  # frozen at the cut, as the live forecast is
    assert tail["base_7d"].iloc[0] == pytest.approx(days[days.index < cut.date()].mean(), rel=0.2)


def test_the_holdout_reports_relative_errors_and_the_means_misses():
    x, y = synthetic(60)
    m = holdout(x, y, "Asia/Ho_Chi_Minh", days=14)
    assert m["wape_model"] == pytest.approx(m["mae_model"] / m["mean_kwh"])
    assert m["wape_base"] == pytest.approx(m["mae_base"] / m["mean_kwh"])
    assert m["base_q10"] <= m["base_q90"]


async def test_device_outlook_shows_the_model_or_falls_back_to_the_weekday_mean(monkeypatch):
    from app.modules.expect.services import device as dev

    x, y = synthetic(40)
    b = refresh.fit_bundle(x, y, "dev", "Asia/Ho_Chi_Minh")
    now = datetime(2026, 2, 9, 17, tzinfo=UTC)  # local midnight in Hanoi
    hi = datetime(2026, 2, 11, 17, tzinfo=UTC)  # two local days

    async def bundle(*a):
        return b

    async def tz(*a):
        return "Asia/Ho_Chi_Minh"

    async def frame(s, h, d, lo, hi_, now_, home_x=None):
        return x.reindex(pd.date_range(lo, hi_, freq="h", inclusive="left")).ffill().bfill()

    async def actual(s, d, lo, hi_):
        idx = pd.date_range(lo, hi_, freq="h", inclusive="left")
        return pd.Series(0.5, index=idx)

    for name, fn in (
        ("active_bundle", bundle),
        ("_tz", tz),
        ("device_frame", frame),
        ("device_actual", actual),
    ):
        monkeypatch.setattr(dev, name, fn)
    b.metrics["backtest"] = {"mae_model": 1, "mae_base": 2, "wape_model": 0.2, "days": 14}
    got = await dev.device_outlook(None, None, None, now, hi)
    assert got["method"] == "model" and got["confidence"] == "high"
    days = [d["date"].isoformat() for d in got["days"]]
    assert days[:2] == ["2026-02-10", "2026-02-11"] and len(days) >= 8  # local days, a week ahead
    assert {f["key"] for f in got["explain"]["all"]} >= {"temperature", "calendar", "trend"}
    b.metrics["backtest"] = {
        "mae_model": 2,
        "mae_base": 1,
        "wape_base": 0.6,
        "days": 14,
        "base_q10": 0.5,
        "base_q90": 2.0,
    }
    got = await dev.device_outlook(None, None, None, now, hi)
    assert (got["method"], got["confidence"]) == ("weekday", "low")
    assert got["explain"]["factors"] == [] and got["explain"]["usual"] == pytest.approx(12.0)
    assert got["days"][0]["p50"] == pytest.approx(12.0)  # 0.5 kWh × 24 h
    assert (got["days"][0]["p10"], got["days"][0]["p90"]) == (
        pytest.approx(6.0),
        pytest.approx(24.0),
    )


async def test_the_running_hour_counts_by_its_rest(monkeypatch):
    from app.modules.expect.services import device as dev

    x, y = synthetic(40)
    b = refresh.fit_bundle(x, y, "dev", "Asia/Ho_Chi_Minh")
    b.metrics["backtest"] = {"mae_model": 2, "mae_base": 1, "wape_base": 0.6, "days": 14}
    now = datetime(2026, 2, 9, 16, 30, tzinfo=UTC)  # 23:30 in Hanoi: half of the day's last hour
    hi = datetime(2026, 2, 11, 17, tzinfo=UTC)

    async def bundle(*a):
        return b

    async def tz(*a):
        return "Asia/Ho_Chi_Minh"

    async def actual(s, d, lo, hi_):
        return pd.Series(0.5, index=pd.date_range(lo, hi_, freq="h", inclusive="left"))

    for name, fn in (("active_bundle", bundle), ("_tz", tz), ("device_actual", actual)):
        monkeypatch.setattr(dev, name, fn)
    got = await dev.device_outlook(None, None, None, now, hi)
    first = got["days"][0]
    assert first["date"].isoformat() == "2026-02-09"
    assert first["p50"] == pytest.approx(0.25)  # 0.5 kWh an hour, 30 minutes left


def _frames(days, start, temp, contrib):
    """Hourly model output and inputs over whole UTC days (tz UTC in these tests)."""
    idx = pd.date_range(start, periods=days * 24, freq="h", tz="UTC")
    p = pd.DataFrame(0.0, index=idx, columns=["p50", "c_calendar", "c_occupancy", "c_trend"])
    for name, per_hour in contrib.items():
        p[name] = per_hour
    p["p50"] = 0.5 + p.drop(columns="p50").sum(axis=1)
    x = pd.DataFrame(
        {
            "temp_c": temp,
            "humidity_pct": 80.0,
            "radiation_wm2": 50.0,
            "precip_mm": 0.0,
            "holiday": 0.0,
            "weekday": idx.day_of_week,
            "presence": 0.5,
            "base_7d": 12.0,
        },
        index=idx,
    )
    return p, x


def test_the_explanation_adds_up_to_the_change_from_usual():
    from app.modules.expect.services.device import explain_outlook

    # 28 past days at 9 °C, 7 days ahead at 5 °C: the heater's temperature share rises 0.1 kWh an
    # hour (2.4 kWh a day); the past actuals ran 0.5 kWh a day over the model (the rest)
    past_p, past_x = _frames(28, "2026-01-01", 9.0, {"f_temp_c": 0.1, "f_humidity_pct": 0.0})
    fut_p, fut_x = _frames(7, "2026-01-29", 5.0, {"f_temp_c": 0.2, "f_humidity_pct": 0.001})
    actual = past_p["p50"] + 0.5 / 24
    e = explain_outlook(fut_p, fut_x, past_p, past_x, actual, "UTC")
    assert e["usual"] == pytest.approx(24 * 0.6 + 0.5)  # 14.9 kWh a day
    assert e["forecast"] == pytest.approx(24 * 0.701)
    [temp] = e["factors"]  # humidity's 0.024 kWh a day is under 5 % of usual
    assert temp["key"] == "temperature" and temp["kwh_day"] == pytest.approx(2.4)
    assert (temp["now"], temp["before"]) == (pytest.approx(5.0), pytest.approx(9.0))
    total = sum(f["kwh_day"] for f in e["all"]) + e["other"]
    assert total == pytest.approx(e["forecast"] - e["usual"])  # the lines add up to the change


def test_days_off_and_trend_bring_their_evidence():
    from app.modules.expect.services.device import explain_outlook

    past_p, past_x = _frames(28, "2026-01-01", 9.0, {})
    fut_p, fut_x = _frames(7, "2026-01-29", 9.0, {"c_calendar": -0.05, "c_trend": 0.08})
    fut_x.loc[fut_x.index.normalize() == pd.Timestamp("2026-01-30", tz="UTC"), "holiday"] = 1.0
    fut_x["base_7d"] = 15.0
    e = explain_outlook(fut_p, fut_x, past_p, past_x, past_p["p50"], "UTC")
    got = {f["key"]: f for f in e["factors"]}
    assert got["trend"]["now"] == 15.0 and got["trend"]["before"] == pytest.approx(12.0)
    # 7 days ahead hold 2 weekend days and a holiday on a Friday: 3; the past weeks 2 a week
    assert (got["calendar"]["now"], got["calendar"]["before"]) == (3, pytest.approx(2.0))


def _real(level_ahead: float):
    """A fitted model's output on its last 28 days and on the same week again ahead, with the
    device's level (base_7d) ahead at `level_ahead` times the past's: inputs otherwise alike."""
    from app.modules.expect.services.predict import predict as run

    x, y = synthetic(60)
    x["base_7d"] = 24.0
    b = refresh.fit_bundle(x, y, "dev", "UTC")
    past_x = x.iloc[-28 * 24 :]
    ahead_x = past_x.iloc[-7 * 24 :].copy()
    ahead_x.index = ahead_x.index + pd.Timedelta(days=7)
    ahead_x["base_7d"] *= level_ahead
    return run(b, past_x, True), past_x, run(b, ahead_x, True), ahead_x


def test_a_level_move_is_the_trend_not_the_weather():
    from app.modules.expect.services.device import explain_outlook

    def run(level):
        past_p, past_x, fut_p, fut_x = _real(level)
        e = explain_outlook(fut_p, fut_x, past_p, past_x, past_p["p50"], "UTC")
        return e, {f["key"]: f["kwh_day"] for f in e["all"]}

    same, a = run(1.0)
    up, b = run(1.5)  # the same week ahead, the device's level up by half
    assert b["temperature"] == pytest.approx(a["temperature"])  # weather's share does not move
    moved = (up["forecast"] - up["usual"]) - (same["forecast"] - same["usual"])
    assert b["trend"] - a["trend"] == pytest.approx(moved)  # the level's move is all trend
    assert sum(b.values()) + up["other"] == pytest.approx(up["forecast"] - up["usual"])


def test_no_factors_when_the_model_misses_the_past_it_explains():
    from app.modules.expect.services.device import explain_outlook

    past_p, past_x, fut_p, fut_x = _real(1.0)
    e = explain_outlook(fut_p, fut_x, past_p, past_x, past_p["p50"] * 3, "UTC")
    assert e["explainable"] is False and e["factors"] == []
    ok = explain_outlook(fut_p, fut_x, past_p, past_x, past_p["p50"] * 1.05, "UTC")
    assert ok["explainable"] is True


def test_the_trend_names_last_weeks_weather_only_for_a_device_it_moves():
    from app.modules.expect.services.device import explain_outlook

    def run(trend, responds=True):
        past_p, past_x = _frames(28, "2026-01-01", 9.0, {})
        cold = past_x.index >= pd.Timestamp("2026-01-22", tz="UTC")
        past_x.loc[cold, "temp_c"] = 5.0  # the last week was colder
        heat = {}
        if responds:  # a heater: more the colder it is, ahead (5 °C) as in the past
            past_p["f_temp_c"] = 0.1 * (16 - past_x["temp_c"])
            past_p["p50"] += past_p["f_temp_c"]
            heat = {"f_temp_c": 0.1 * (16 - 5.0)}
        fut_p, fut_x = _frames(7, "2026-01-29", 5.0, {"c_trend": trend, **heat})
        e = explain_outlook(fut_p, fut_x, past_p, past_x, past_p["p50"], "UTC")
        return next(f for f in e["all"] if f["key"] == "trend")

    up = run(0.08)  # using more after a colder week: the weather fits
    assert up["recent_temp"] == pytest.approx(5.0)
    assert up["usual_temp"] == pytest.approx((21 * 9 + 7 * 5) / 28)
    assert run(-0.08)["recent_temp"] is None  # using less after a colder week: it does not
    assert run(0.08, responds=False)["recent_temp"] is None  # a device the weather does not move


def test_usual_and_the_models_past_cover_the_same_days():
    from app.modules.expect.services.device import explain_outlook

    past_p, past_x = _frames(28, "2026-01-01", 9.0, {})
    gap = past_p.index >= pd.Timestamp("2026-01-22", tz="UTC")  # NILM has nothing for a week
    past_p.loc[gap, "p50"] = 3.0  # the model expects a lot on those days
    actual = past_p["p50"].where(~gap)
    fut_p, fut_x = _frames(7, "2026-01-29", 9.0, {})
    e = explain_outlook(fut_p, fut_x, past_p, past_x, actual, "UTC")
    assert e["explainable"] is True  # judged on the 21 measured days only
    assert e["other"] == pytest.approx(0.0)


async def test_a_devices_level_is_its_mean_of_the_seven_full_days_before(monkeypatch):
    from datetime import date

    from app.modules.expect.services import device as dev

    async def tz(*a):
        return "Asia/Ho_Chi_Minh"

    seen = []

    async def daily(s, device_id, lo, hi, tz_):
        seen.append((lo, hi))
        days = pd.date_range("2026-11-10", "2026-11-19", freq="D").date
        return pd.Series([1.0, 1.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0, np.nan, 9.0], index=days)

    monkeypatch.setattr(dev, "_tz", tz)
    monkeypatch.setattr(dev, "_device_daily", daily)
    # The 12th to the 18th (not full: left out); the 19th itself and the 11th are outside.
    got = await dev.device_level(None, None, None, date(2026, 11, 19))
    assert got == 2.0
    [(lo, hi)] = seen
    assert hi == pd.Timestamp("2026-11-18T17:00Z")  # the 19th's midnight in Hanoi


def test_the_holdout_asks_tail_as_of_for_its_inputs(monkeypatch):
    from app.modules.expect.services import device as dev

    seen = []
    real = dev.tail_as_of

    def spy(x, y, tz, cut):
        seen.append(cut)
        return real(x, y, tz, cut)

    monkeypatch.setattr(dev, "tail_as_of", spy)
    x, y = synthetic(60)
    dev.holdout(x, y, "Asia/Ho_Chi_Minh", days=14)
    assert seen == [y.index[-1] - pd.Timedelta(days=14)]
