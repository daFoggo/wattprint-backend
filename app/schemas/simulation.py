import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field

SimulationStatus = Literal["pending", "running", "done", "failed", "cancelled"]


class SimulationCreate(BaseModel):
    date: dt.date = Field(description="REFIT day to replay, as stored in the CSV (UTC), YYYY-MM-DD")
    house: int = Field(2, ge=1, description="REFIT house number; its CSV must be available")
    replay_date: dt.date | None = Field(
        None,
        description=(
            "Calendar day (Asia/Ho_Chi_Minh) the replayed data is stored under. The raw tables "
            "drop data older than 400 days and the aggregates only refresh the last 7 days, so "
            "it must lie within the last 6 days. Default: yesterday."
        ),
    )
    rows_per_second: float = Field(
        10.0, gt=0, le=500, description="Minutes of data processed per real second (upper bound)"
    )


class SimulationOut(BaseModel):
    id: int = Field(description="energy.inference_run.run_id of this replay")
    status: SimulationStatus
    house: int | None = None
    source_date: dt.date | None = Field(None, description="REFIT day being replayed")
    replay_date: dt.date = Field(description="Day (Asia/Ho_Chi_Minh) the data is stored under")
    rows_per_second: float | None = None
    total_minutes: int | None = None
    done_minutes: int | None = None
    progress_pct: float | None = None
    error: str | None = None
    started_at: dt.datetime | None = None
    finished_at: dt.datetime | None = None
