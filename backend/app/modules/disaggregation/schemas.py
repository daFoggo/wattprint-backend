from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class BreakdownItem(BaseModel):
    appliance: str
    kwh: float
    percent: float
    true_kwh: float | None = None          # kWh theo sub-meter (nếu có)
    accuracy_pct: float | None = None      # độ khớp theo từng phút
    energy_error_pct: float | None = None  # (dự đoán - thật) / thật


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
    explained_pct: float | None = None     # % aggregate được 4 thiết bị giải thích
    accuracy_pct: float | None = None      # độ khớp tổng thể so với thực tế
    breakdown: list[BreakdownItem]
    hourly: list[HourlyPoint] | None = None
    daily: list[DailyPoint] | None = None
class LatestPoint(BaseModel):
    ts: datetime
    aggregate_w: float
    appliances_w: dict[str, float] | None = None
    other_w: float | None = None           # aggregate - tổng các thiết bị
    truth_w: dict[str, float] | None = None   # số đo thật (sub-meter), nếu có
    error_w: dict[str, float] | None = None   # truth - dự đoán (W); dương = model đoán thấp          # aggregate - tổng các thiết bị
class LatestOut(BaseModel):
    house_id: int
    points: list[LatestPoint]

class SimulationCreate(BaseModel):
    date: date  # ngày cần mô phỏng (UTC), YYYY-MM-DD
    rows_per_second: float = Field(10.0, gt=0, le=500, description="phút dữ liệu xử lý mỗi giây thật")

class SimulationOut(BaseModel):
    id: int
    house_id: int
    day: date
    status: str
    rows_per_second: float
    total_minutes: int | None = None
    done_minutes: int = 0
    progress_pct: float = 0.0
    error: str | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None