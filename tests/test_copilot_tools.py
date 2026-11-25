from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pandas as pd
import pytest
from sqlalchemy import text

from app.database import SessionLocal
from app.modules.billing.services.forecast import Accuracy, Change, Forecast, TierCross
from app.modules.copilot.services import tools


def frame(actual: list[float], weather: list[float]) -> pd.DataFrame:
    n = len(actual)
    return pd.DataFrame(
        {
            "kwh": actual,
            "p50": [1.0] * n,
            "c_weather": weather,
            "c_calendar": [0.1] * n,
            "c_occupancy": [0.0] * n,
            "c_trend": [0.0] * n,
            "c_base": [0.5] * n,
        }
    )


def test_explain_usage_parts_sum_to_change():
    got = tools.explain_parts(frame([2.0, 2.0], [0.6, 0.6]), frame([1.0, 1.0], [0.1, 0.1]))
    assert got["actual_kwh"] == 4.0 and got["previous_actual_kwh"] == 2.0
    assert got["change_kwh"] == 2.0
    assert got["parts_kwh"]["weather"] == pytest.approx(1.0)
    assert sum(got["parts_kwh"].values()) == pytest.approx(got["change_kwh"])


async def test_explain_usage_without_model_says_so(make_member):
    me = await make_member("owner")
    async with SessionLocal() as s:
        ctx = tools.Ctx(s, me.home_id, datetime.now(UTC), "vi")
        out = await tools.explain_usage(ctx, "week")
    assert "error" in out.data


@pytest.mark.parametrize("minute", [0, 30, 59])
async def test_explain_usage_today_in_the_first_hour_says_no_whole_hour(make_member, minute):
    me = await make_member("owner")
    at = datetime(2026, 11, 24, 0, minute, tzinfo=timezone(timedelta(hours=7))).astimezone(UTC)
    async with SessionLocal() as s:
        out = await tools.explain_usage(tools.Ctx(s, me.home_id, at, "vi"), "today")
    assert "whole hour" in out.data["error"] and "model" not in out.data["error"]


def test_bill_forecast_carries_range():
    bill = SimpleNamespace(
        kwh=Decimal(100), tier_no=2, tiers=[SimpleNamespace(tier_no=2, to_kwh=Decimal(100))]
    )
    f = Forecast(
        period_start=date(2026, 11, 1),
        period_end=date(2026, 11, 30),
        kwh=Decimal(210),
        amount=Decimal(650000),
        tier_no=4,
        next=TierCross(4, Decimal(201), Decimal(2900), date(2026, 11, 26), 0.7),
        basis_days=200,
        as_of=date(2026, 11, 21),
        method="context",
        model_version="ctx-v1-x",
        kwh_p10=Decimal(200),
        kwh_p50=Decimal(210),
        kwh_p90=Decimal(225),
        amount_p10=Decimal(620000),
        amount_p90=Decimal(700000),
        change=Change(Decimal(35000), {"weather": Decimal(28000), "used": Decimal(7000)}),
        accuracy=Accuracy("backtest", 0.041, 6),
        simulated=["heater"],
    )
    data = tools.forecast_data(bill, f)
    assert data["kwh_range"] == [200.0, 225.0]
    assert data["amount_vnd_range"] == [620000.0, 700000.0]
    assert data["next_tier"]["probability"] == 0.7
    assert data["change"]["parts_vnd"]["weather"] == 28000.0
    assert data["method"].startswith("contextual model")
    assert data["simulated"] == ["heater"] and data["accuracy"]["error_pct"] == 0.041


def test_explain_usage_compares_only_hours_known_in_both_periods():
    import numpy as np

    cur = frame([2.0, 2.0, 2.0], [0.1, 0.1, 0.1])
    prev = frame([1.0, np.nan, 1.0], [0.1, 0.1, 0.1])
    lo, prev_lo = pd.Timestamp("2026-11-10", tz="UTC"), pd.Timestamp("2026-10-10", tz="UTC")
    cur.index = pd.date_range(lo, periods=3, freq="h")
    prev.index = pd.date_range(prev_lo, periods=3, freq="h")
    a, b = tools.align(cur, prev, lo, prev_lo)
    assert len(a) == len(b) == 2
    assert tools.explain_parts(a, b)["change_kwh"] == 2.0  # 4 - 2, the gap hour left out of both


async def test_a_demo_viewer_s_wappi_sets_no_watch(make_member):
    me = await make_member(role="viewer")
    async with SessionLocal() as s:
        ctx = tools.Ctx(s, me.home_id, datetime.now(UTC), "vi", user_id=me.user_id, read_only=True)
        args = {"metric": "power_w", "op": "gt", "threshold": 1, "label": "x"}
        outcome, ok, _ = await tools.run_tool(ctx, "create_watch", args)
        assert not ok and "read-only" in outcome.data["error"]
        n = await s.scalar(
            text("SELECT count(*) FROM public.tb_watch WHERE home_id = :h"), {"h": me.home_id}
        )
        assert n == 0


def _dev(name, method="model", advice=None):
    import uuid

    from app.modules.billing.services.device_forecast import Advice, Day, DeviceForecast

    return DeviceForecast(
        uuid.uuid4(),
        name,
        "kettle",
        False,
        method,
        "medium",
        32.5,
        14,
        [Day(date(2026, 11, 23), Decimal("0.4"), None, None, Decimal(1200))],
        Decimal("3.2"),
        Decimal("2.4"),
        Decimal("4.0"),
        Decimal(9600),
        None,
        advice
        if advice is not None
        else [Advice("kettle_fill", Decimal("0.96"), Decimal(5100), None, {"share": 30})],
    )


def _forecasts(devices):
    from app.modules.billing.services.device_forecast import DeviceForecasts

    async def forecasts(*a):
        return DeviceForecasts(date(2026, 11, 30), date(2026, 11, 23), devices)

    return forecasts


async def test_device_forecast_hands_the_model_every_figure(monkeypatch):
    kettle = _dev("Kettle")
    monkeypatch.setattr(tools, "device_forecasts", _forecasts([kettle, _dev("Toaster", "weekday")]))
    ctx = tools.Ctx(None, None, datetime(2026, 11, 23, 3, tzinfo=UTC), "vi")
    got = await tools.device_forecast(ctx, "kettle")
    [k] = got.data["devices"]
    assert k["device"] == "Kettle" and k["certainty"] == "medium"
    assert k["tried_on"] == {"days": 14, "mean_error_pct": 32.5}
    assert k["to_cycle_end"] == {"kwh": 3.2, "vnd": 9600, "kwh_range": [2.4, 4.0]}
    assert k["advice"] == [
        {
            "id": f"{kettle.device_id}.kettle_fill",
            "what": "kettle_fill",
            "saves_vnd": 5100,
            "saves_kwh": 1.0,
            "keeps_out_of_tier": None,
            "share": 30,
        }
    ]
    assert len((await tools.device_forecast(ctx)).data["devices"]) == 2


async def test_propose_plan_keeps_only_todays_advice_and_prices_it(monkeypatch, make_member):
    from app.modules.billing.services.device_forecast import Advice

    washer = _dev(
        "Washer",
        advice=[
            Advice("fewer_runs", Decimal("4.5"), Decimal(12000), 3, {"runs_per_week": 5}),
        ],
    )
    kettle = _dev("Kettle")
    monkeypatch.setattr(tools, "device_forecasts", _forecasts([kettle, washer]))
    me = await make_member(role="viewer")  # a read: a demo viewer's Wappi proposes too
    w_id, k_id = f"{washer.device_id}.fewer_runs", f"{kettle.device_id}.kettle_fill"
    async with SessionLocal() as s:
        ctx = tools.Ctx(s, me.home_id, datetime(2026, 11, 23, 3, tzinfo=UTC), "vi", read_only=True)
        out, ok, _ = await tools.run_tool(
            ctx, "propose_plan", {"actions": [w_id, "nope.kettle_fill", w_id, k_id]}
        )
        assert ok, out.data
        [widget] = out.widgets
        assert [a.id for a in widget.actions] == [w_id, k_id]  # in order, once
        assert widget.actions[0].model_dump() == {
            "id": w_id,
            "key": "fewer_runs",
            "device": "Washer",
            "params": {"runs_per_week": 5},
            "kwh": 4.5,
            "vnd": 12000,
        }
        assert (widget.kwh, widget.vnd) == (5.46, 17100)
        assert out.data["unknown"] == ["nope.kettle_fill"]

        out, ok, _ = await tools.run_tool(ctx, "propose_plan", {"actions": ["nope.kettle_fill"]})
        assert not ok and "device_forecast" in out.data["error"]
        n = await s.scalar(
            text("SELECT count(*) FROM public.tb_suggestion WHERE home_id = :h"), {"h": me.home_id}
        )
        assert n == 0
