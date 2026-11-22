import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


class WatchRead(BaseModel):
    """A threshold the user asked Wappi to watch; `label` is in the words they used."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    label: str
    metric: str
    device_id: uuid.UUID | None
    op: str
    threshold: Decimal
    unit: str
    status: str
    repeat: bool
    last_value: Decimal | None
    last_checked_at: datetime | None
    fired_at: datetime | None
    ends_at: datetime
    created_at: datetime


class WatchCreate(BaseModel):
    """A threshold set by hand; a custom query (metric `sql`) is set through Wappi only."""

    metric: Literal[
        "bill_vnd",
        "bill_kwh",
        "forecast_vnd",
        "today_kwh",
        "power_w",
        "device_kwh_today",
        "device_on",
        "device_off",
        "device_run_min",
        "device_power_w",
    ]
    op: Literal["gt", "lt"]
    threshold: float = Field(allow_inf_nan=False)
    label: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    device_id: uuid.UUID | None = None
    ends_on: date | None = None
    repeat: bool = True


class WatchCreated(WatchRead):
    value_now: Decimal | None
