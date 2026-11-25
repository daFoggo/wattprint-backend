from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict


class TierUse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tier_no: int
    from_kwh: float
    to_kwh: float | None
    price_per_kwh: float
    kwh: float
    amount: float


class CurrentBill(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    period_start: date
    period_end: date
    status: str
    coverage: float
    tariff_straddle: bool
    vat_rate: float
    tariff_doc: str | None
    kwh: float
    amount_before_vat: float
    vat_amount: float
    amount_total: float
    tier_no: int
    tiers: list[TierUse]
    today_kwh: float
    today_amount: float


class PastBill(BaseModel):
    """One ended billing cycle as stored in tb_bill. coverage < 0.95 means readings are missing."""

    model_config = ConfigDict(from_attributes=True)

    period_start: date
    period_end: date
    kwh: float
    amount: float
    coverage: float
    tariff_straddle: bool


class TierCross(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tier_no: int
    from_kwh: float
    price_per_kwh: float
    on: date
    probability: float | None = None  # share of the model's draws passing it; None for weekday


class ForecastChange(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    amount: float  # VND against yesterday's forecast
    parts: dict[str, float]  # used, weather, calendar, occupancy, trend, unexplained (VND)


class ForecastAccuracy(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source: Literal["cycle", "backtest"]
    error_pct: float
    cycles: int


class Forecast(BaseModel):
    """The running cycle at its end: from the home's expected-usage model (`context`) or, without
    one, its usual weekday pattern (`weekday`). kwh/amount are the middle (P50); the range is
    P10–P90."""

    model_config = ConfigDict(from_attributes=True)

    period_start: date
    period_end: date
    kwh: float
    amount: float
    tier_no: int
    next: TierCross | None
    basis_days: int
    as_of: date  # the local day it was made on: how much of the cycle is behind it
    method: Literal["context", "weekday"]
    model_version: str
    kwh_p10: float
    kwh_p50: float
    kwh_p90: float
    amount_p10: float
    amount_p90: float
    change: ForecastChange | None
    accuracy: ForecastAccuracy | None
    simulated: list[str]
