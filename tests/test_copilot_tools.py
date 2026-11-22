from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pandas as pd
import pytest

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
