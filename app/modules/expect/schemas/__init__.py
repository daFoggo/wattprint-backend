from datetime import datetime

from pydantic import BaseModel


class ExpectedHour(BaseModel):
    """The model's expected kWh for an hour (P10–P90 range, P50 the usual) and what the meter
    measured (None while the hour runs or when it reported under 54 minutes)."""

    ts: datetime
    p10: float
    p50: float
    p90: float
    kwh: float | None
