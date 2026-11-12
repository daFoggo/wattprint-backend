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
