import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pandas as pd
import pytest

from app.modules.billing.services import device_forecast as dfc

NOW = datetime(2026, 11, 23, 3, tzinfo=UTC)  # 10:00 in Hanoi


def test_one_run_fewer_a_week_only_for_a_device_run_twice_a_week():
    assert dfc.fewer_runs(12, 1.2, 14) == pytest.approx(2.4)  # 3 a week; 2 weeks left
    assert dfc.fewer_runs(6, 1.2, 14) is None  # 1.5 a week: nothing to cut


def test_heater_saving_is_the_formula_with_the_new_setpoint():
    idx = pd.date_range("2026-11-23 11:00", periods=2, freq="h", tz="UTC")  # 18:00, 19:00 local
    temps = pd.Series([6.0, 10.0], index=idx)
    params = {"setpoint_c": 16.0, "w_per_c": 180.0, "max_w": 2000.0, "hours": [[17, 23]]}
    got = dfc.heater_saving(temps, "Asia/Ho_Chi_Minh", params, {"setpoint_c": 14.0})
    assert got == pytest.approx(2 * 180 * 2 / 1000)  # 2 °C × 180 W/°C, two hours


@pytest.fixture
def home(monkeypatch):
    tiers = [
        SimpleNamespace(tier_no=1, from_kwh=Decimal(0)),
        SimpleNamespace(tier_no=2, from_kwh=Decimal(100)),
    ]
    segments = [SimpleNamespace(start=date(2026, 11, 1), tiers=tiers)]
    forecast = SimpleNamespace(
        kwh=Decimal(110), amount=Decimal(330000), period_end=date(2026, 11, 30), tier_no=2
    )
    washer, fridge = uuid.uuid4(), uuid.uuid4()

    async def bill(*a):
        return forecast

    async def price(*a):
        return None, segments, None

    async def outlook(s, h, d, now, hi, x):
        if d == fridge:  # its model lost: the weekday mean, no reasons
            return {
                "method": "weekday",
                "confidence": "low",
                "wape": 0.7,
                "backtest_days": 14,
                "explain": {
                    "usual": 1.0,
                    "forecast": 1.0,
                    "explainable": False,
                    "factors": [],
                    "all": [],
                    "other": 0.0,
                },
                "days": [{"date": date(2026, 11, 23), "p10": None, "p50": 1.0, "p90": None}],
            }
        return {
            "method": "model",
            "confidence": "high",
            "wape": 0.2,
            "backtest_days": 14,
            "explain": {
                "usual": 0.8,
                "forecast": 1.0,
                "explainable": True,
                "factors": [{"key": "temperature", "kwh_day": 0.5, "now": 5.04, "before": 9.0}],
                "all": [],
                "other": -0.3,
            },
            "days": [
                {
                    "date": date(2026, 11, 23) + pd.Timedelta(days=k),
                    "p10": 0.8,
                    "p50": 1.0,
                    "p90": 1.3,
                }
                for k in range(8)
            ],
        }

    async def devices(*a):
        return [
            SimpleNamespace(id=washer, name="Washing Machine", type="washing_machine"),
            SimpleNamespace(id=fridge, name="Fridge-Freezer", type="fridge_freezer"),
        ]

    async def runs(*a):
        return 16, 1.5  # 4 a week, 1.5 kWh each

    async def none(*a, **k):
        return None

    async def empty(*a, **k):
        return []

    class S:
        async def get(self, *a):
            return SimpleNamespace(billing_cycle_day=1, timezone="Asia/Ho_Chi_Minh")

    for name, fn in (
        ("forecast_bill", bill),
        ("_price", price),
        ("device_outlook", outlook),
        ("_devices", devices),
        ("_runs", runs),
        ("_denser_excess", none),
        ("feature_frame", none),
        ("scenarios_between", empty),
    ):
        monkeypatch.setattr(dfc, name, fn)
    monkeypatch.setattr(dfc, "_amounts", lambda segs, k: (k * 3000, Decimal(0)))  # 3.000 ₫/kWh
    return S(), washer, fridge


async def test_each_device_has_its_range_reasons_certainty_and_priced_advice(home):
    s, washer, fridge = home
    got = await dfc.device_forecasts(s, uuid.uuid4(), NOW)
    w, f = got.devices  # by amount: the washer's 8 kWh first
    assert (w.device_id, w.method, w.confidence) == (washer, "model", "high")
    assert len(w.next_days) == 7 and w.kwh == Decimal("8.000")
    assert (w.kwh_p10, w.kwh_p90) == (Decimal("6.400"), Decimal("10.400"))
    e = w.explain  # against its usual: 0.8 → 1.0 kWh a day; colder adds 0.5, the rest −0.3
    assert (e.usual_kwh_day, e.forecast_kwh_day) == (Decimal("0.800"), Decimal("1.000"))
    assert [(x.key, x.amount) for x in e.factors] == [("temperature", 10500), ("other", -6300)]
    assert (e.factors[0].now, e.factors[0].before) == (5.04, 9.0)  # 7 days × 3.000 ₫/kWh above
    assert e.busiest is not None and e.busiest.kwh == Decimal("1.000")
    [a] = w.advice  # one run fewer a week: 1.5 kWh × 8 days / 7
    assert a.key == "fewer_runs" and a.saved_kwh == Decimal("1.714")
    assert a.saved_amount == Decimal(5142) and a.avoids_tier is None
    assert (f.method, f.confidence, f.explain.factors, f.kwh_p10) == ("weekday", "low", [], None)
    assert f.error_pct == 70.0 and f.advice == []  # no open "denser" alert: nothing to check


async def test_advice_that_keeps_the_cycle_out_of_a_tier_says_so(home, monkeypatch):
    s, *_ = home

    async def runs(*a):
        return 28, 9.0  # 7 a week, 9 kWh each: 10.3 kWh saved takes 110 kWh under 100

    monkeypatch.setattr(dfc, "_runs", runs)
    got = await dfc.device_forecasts(s, uuid.uuid4(), NOW)
    assert got.devices[0].advice[0].avoids_tier == 2


async def test_a_home_is_computed_once_an_hour(home, monkeypatch):
    s, *_ = home
    calls = []
    real = dfc.forecast_bill

    async def counted(*a):
        calls.append(1)
        return await real(*a)

    monkeypatch.setattr(dfc, "forecast_bill", counted)
    monkeypatch.setattr(dfc, "_CACHE", {})
    hid = uuid.uuid4()
    first = await dfc.device_forecasts(s, hid, NOW)
    again = await dfc.device_forecasts(s, hid, NOW.replace(minute=40))
    later = await dfc.device_forecasts(s, hid, NOW.replace(hour=4))
    assert again is first and later is not first and len(calls) == 2


async def test_kettle_fridge_and_heater_advice(home, monkeypatch):
    s, *_ = home
    kettle, fridge, heater = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    async def devices(*a):
        return [
            SimpleNamespace(id=kettle, name="Kettle", type="kettle"),
            SimpleNamespace(id=fridge, name="Fridge-Freezer", type="fridge_freezer"),
            SimpleNamespace(id=heater, name="Heater", type="electric_heater"),
        ]

    async def excess(s, d):
        return 0.4 if d == fridge else None  # an open "cycling denser" alert: 0.4 kWh a day more

    sc = SimpleNamespace(name="heater", params={"setpoint_c": 16.0}, ends_at=None)

    async def scen(*a):
        return [sc]

    hours = pd.date_range("2026-11-23 10:00", periods=48, freq="h", tz="UTC")  # 17:00 local on

    async def weather(*a):
        return pd.DataFrame({"temp_c": 6.0}, index=hours)

    for name, fn in (
        ("_devices", devices),
        ("_denser_excess", excess),
        ("scenarios_between", scen),
        ("weather_inputs", weather),
    ):
        monkeypatch.setattr(dfc, name, fn)
    monkeypatch.setattr(dfc, "_CACHE", {})
    got = {d.name: d for d in (await dfc.device_forecasts(s, uuid.uuid4(), NOW)).devices}
    [k] = got["Kettle"].advice
    assert (k.key, k.saved_kwh) == ("kettle_fill", Decimal("2.400"))  # 30 % of its 8 kWh
    [f] = got["Fridge-Freezer"].advice
    assert (f.key, f.saved_kwh) == ("fridge_check", Decimal("3.200"))  # 0.4 kWh × 8 days left
    h = {a.key: a for a in got["Heater"].advice}
    # 6 °C under a 16 °C setpoint: 1800 W in its hours; at 14 °C, 1440 W. The 48 h from 17:00 local
    # hold two evenings 17–23 and two mornings 06–09: 18 hours × 360 W
    assert h["heater_setpoint"].saved_kwh == Decimal("6.480")
    # off at 22:00 instead of 23:00: one hour at 1800 W each evening
    assert h["heater_earlier_off"].saved_kwh == Decimal("3.600")


def test_nilm_pieces_of_one_program_count_as_one_run():
    t = datetime(2026, 11, 20, 1, tzinfo=UTC)
    m = pd.Timedelta(minutes=1)
    pieces = [  # one dishwasher program cut into three by NILM, then another program next day
        (t, t + 20 * m, 400.0),
        (t + 50 * m, t + 70 * m, 300.0),
        (t + 100 * m, t + 120 * m, 300.0),
        (t + pd.Timedelta(days=1), t + pd.Timedelta(days=1) + 90 * m, 1200.0),
        (t + pd.Timedelta(days=2), t + pd.Timedelta(days=2) + 5 * m, 80.0),  # NILM's false start
    ]
    assert dfc.programs(pieces) == (2, pytest.approx(1.1))  # 1.0 and 1.2 kWh; 80 Wh is no wash


def test_a_fit_device_with_no_big_factor_still_says_what_moves_it():
    e = {
        "usual": 1.0,
        "forecast": 0.87,
        "explainable": True,
        "factors": [],
        "all": [],
        "other": -0.13,
    }
    got = dfc._explain(e, [], Decimal(3000))
    assert [f.key for f in got.factors] == ["other"]


async def test_heater_advice_counts_every_hour_to_the_cycle_s_end(home, monkeypatch):
    # weather_inputs fills hours past the 5-day forecast (a year earlier, else the last two weeks),
    # so the saving runs to the cycle's end (8 days left here), not to the forecast's horizon
    s, *_ = home
    heater = uuid.uuid4()

    async def devices(*a):
        return [SimpleNamespace(id=heater, name="Heater", type="electric_heater")]

    async def scen(*a):
        return [SimpleNamespace(name="heater", params={"setpoint_c": 16.0}, ends_at=None)]

    async def weather(s, home_id, lo, hi, now):
        return pd.DataFrame(
            {"temp_c": 6.0}, index=pd.date_range(lo, hi, freq="h", inclusive="left")
        )

    for name, fn in (
        ("_devices", devices),
        ("scenarios_between", scen),
        ("weather_inputs", weather),
    ):
        monkeypatch.setattr(dfc, name, fn)
    monkeypatch.setattr(dfc, "_CACHE", {})
    [d] = (await dfc.device_forecasts(s, uuid.uuid4(), NOW)).devices
    h = {a.key: a for a in d.advice}
    # from 10:00 on 23 Nov to 1 Dec: 8 evenings 17–23 and 7 mornings 06–09 = 69 hours × 360 W
    assert h["heater_setpoint"].saved_kwh == Decimal("24.840")
    assert h["heater_earlier_off"].saved_kwh == Decimal("14.400")  # 8 evenings × 1800 W
