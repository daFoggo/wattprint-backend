from datetime import datetime

from pydantic import BaseModel, ConfigDict


class Power(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ts: datetime
    watts: float


class Today(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    kwh: float
    typical_kwh: float | None


class Overview(BaseModel):
    live: Power | None
    today: Today | None


class SeriesPoint(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ts: datetime
    avg_w: float
    min_w: float
    max_w: float
    energy_wh: float
