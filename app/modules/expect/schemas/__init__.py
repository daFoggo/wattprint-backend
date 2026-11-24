from datetime import datetime

from pydantic import BaseModel


class ExpectedHour(BaseModel):
    """The model's expected kWh for an hour (P10–P90, P50 the mean) and what the meter
    measured (None while the hour runs or when it reported under 54 minutes). `model_version` is
    the model that made it: a refit rewrites past hours, so a client can tell which ones changed."""

    ts: datetime
    p10: float
    p50: float
    p90: float
    kwh: float | None
    model_version: str
