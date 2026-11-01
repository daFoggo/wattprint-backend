from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel


class BreakdownItem(BaseModel):
    appliance: str
    kwh: float
    percent: float


class HourlyPoint(BaseModel):
    hour: datetime
    total_kwh: float
    by_appliance: dict[str, float]


class DailyPoint(BaseModel):
    date: date
    total_kwh: float
    by_appliance: dict[str, float]


class DisaggregationOut(BaseModel):
    house_id: int
    period: Literal["day", "week"]
    start: datetime
    end: datetime
    unit: str = "kWh"
    total_kwh: float
    breakdown: list[BreakdownItem]
    hourly: list[HourlyPoint] | None = None  # chỉ có khi period=day
    daily: list[DailyPoint] | None = None