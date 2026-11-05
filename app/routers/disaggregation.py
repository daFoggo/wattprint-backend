import datetime as dt
from typing import Annotated, Literal

from fastapi import APIRouter, Query

from ..dependencies import CurrentUser, DbSession
from ..schemas.disaggregation import DisaggregationOut, LatestOut
from ..services import disaggregation
from .common import require_home

router = APIRouter(prefix="/disaggregation", tags=["disaggregation"])


@router.get(
    "",
    response_model=DisaggregationOut,
    response_model_exclude_none=True,
    summary="Energy per appliance over one day or one week",
)
async def get_report(
    user: CurrentUser,
    db: DbSession,
    date: Annotated[
        dt.date, Query(description="First day, YYYY-MM-DD, a calendar day of Asia/Ho_Chi_Minh")
    ],
    period: Literal["day", "week"] = "day",
) -> DisaggregationOut:
    """kWh per appliance estimated by the model, the rest as `other`.

    Where the home has plug sub-meters the response also holds the true kWh, the energy error
    and the per-minute accuracy. `period=day` adds 24 hourly points, `period=week` 7 daily ones.
    """
    home_id = await require_home(db, user)
    return await disaggregation.report(db, home_id, period, date)


@router.get("/latest", summary="The newest minutes: aggregate, estimates, sub-meters and error")
async def get_latest(
    user: CurrentUser,
    db: DbSession,
    minutes: Annotated[int, Query(ge=1, le=1440)] = 30,
) -> LatestOut:
    """`error_w` is the sub-meter reading minus the model estimate (W) per appliance."""
    home_id = await require_home(db, user)
    return await disaggregation.latest(db, home_id, minutes)
