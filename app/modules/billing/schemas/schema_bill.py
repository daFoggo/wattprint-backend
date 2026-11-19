from datetime import date

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


class Forecast(BaseModel):
    """The running cycle at its end if the home keeps its usual weekday pattern."""

    model_config = ConfigDict(from_attributes=True)

    period_start: date
    period_end: date
    kwh: float
    amount: float
    tier_no: int
    next: TierCross | None
    basis_days: int
    as_of: date  # the local day it was made on: how much of the cycle is behind it
