import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

Number = Annotated[float, Field(allow_inf_nan=False)]


class PlanAction(BaseModel):
    """One action as the page priced it; the measurement does not rest on these numbers."""

    device_id: uuid.UUID | None
    key: Literal[
        "fewer_runs",
        "kettle_fill",
        "fridge_check",
        "heater_setpoint",
        "heater_earlier_off",
        "always_on",
    ]
    label: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    kwh: Number
    amount: Number
    baseline: Number | None
    watts: Number | None


class PlanCreate(BaseModel):
    start_on: date
    actions: list[PlanAction]


class DeviceDay(BaseModel):
    expected: float
    actual: float


class PlanDay(BaseModel):
    """`expected` and `actual` are the home's; `devices` the planned devices measured against
    their own model (the trusted ones), keyed by device id."""

    date: date
    expected: float
    actual: float
    devices: dict[uuid.UUID, DeviceDay] = {}


class PlanRead(BaseModel):
    """A savings plan with its frozen days: `expected` already carries the model's mean error."""

    id: uuid.UUID
    start_on: date
    end_on: date
    model_version: str
    sigma: float | None
    bias: float
    forecast_kwh: float
    actions: list[PlanAction]
    days: list[PlanDay]
    status: Literal["active", "stopped"]
    created_at: datetime


class PlanHistoryItem(PlanRead):
    """A finished plan; `mine` is false for a home owner's plan seen by another member."""

    stopped_at: datetime | None
    mine: bool


class PlanBasis(BaseModel):
    """What a plan started now would be measured against (`GET /insights/plans/basis`)."""

    model_version: str
    sigma: float | None
    bias: float
    earliest_start: date
    period_end: date
