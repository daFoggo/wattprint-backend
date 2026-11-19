from datetime import date

from pydantic import BaseModel, ConfigDict


class Cohort(BaseModel):
    """Similar homes over `days` whole days ending `period`: kWh percentiles, and this home's."""

    model_config = ConfigDict(from_attributes=True)

    cohort_key: str  # the home type compared against, or "all"
    period: date
    days: int
    homes: int
    p10: float
    p33: float
    p66: float
    p90: float
    kwh: float | None
