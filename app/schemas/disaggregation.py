import datetime as dt
import uuid
from typing import Literal

from pydantic import BaseModel, Field


class BreakdownItem(BaseModel):
    appliance: str = Field(description="catalog.device_type code, or 'other'")
    name: str | None = None
    device_id: uuid.UUID | None = None
    kwh: float = Field(description="Energy estimated by the model")
    percent: float = Field(description="Share of the whole-home energy")
    true_kwh: float | None = Field(None, description="Energy of the plug sub-meter, if any")
    energy_error_pct: float | None = Field(None, description="(estimated - true) / true * 100")
    accuracy_pct: float | None = Field(
        None, description="Per-minute match: 100 * (1 - sum|est - true| / (2 * sum true))"
    )


class HourlyPoint(BaseModel):
    hour: dt.datetime
    total_kwh: float
    by_appliance: dict[str, float]


class DailyPoint(BaseModel):
    day: dt.date
    total_kwh: float
    by_appliance: dict[str, float]


class DisaggregationOut(BaseModel):
    home_id: uuid.UUID
    period: Literal["day", "week"]
    start: dt.datetime
    end: dt.datetime
    timezone: str = "Asia/Ho_Chi_Minh"
    unit: str = "kWh"
    total_kwh: float
    explained_pct: float | None = Field(
        None, description="Share of the whole-home energy explained by the tracked appliances"
    )
    accuracy_pct: float | None = Field(
        None, description="Per-minute match over all tracked appliances with a sub-meter"
    )
    breakdown: list[BreakdownItem]
    hourly: list[HourlyPoint] | None = None  # period=day
    daily: list[DailyPoint] | None = None  # period=week


class LatestPoint(BaseModel):
    ts: dt.datetime
    aggregate_w: float
    appliances_w: dict[str, float] | None = Field(
        None, description="Model estimate per appliance; null until the minute is predicted"
    )
    other_w: float | None = Field(None, description="aggregate - sum of the appliances")
    truth_w: dict[str, float] | None = Field(None, description="Plug sub-meter reading")
    error_w: dict[str, float] | None = Field(
        None, description="truth - estimate in W; positive means the model under-estimates"
    )


class LatestOut(BaseModel):
    home_id: uuid.UUID
    points: list[LatestPoint]  # oldest first
