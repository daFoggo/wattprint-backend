from datetime import date
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from app.api.deps import DbSession
from app.core.security import CurrentUser

from .models import House
from .schemas import DisaggregationOut
from .service import get_disaggregation

router = APIRouter(prefix="/houses", tags=["disaggregation"])


@router.get(
    "/{house_id}/disaggregation",
    response_model=DisaggregationOut,
    response_model_exclude_none=True,  # day -> chỉ có "hourly", week -> chỉ có "daily"
    summary="Energy breakdown per appliance for one day / one week (UTC)",
)
async def disaggregation(
    house_id: int,
    user: CurrentUser,
    db: DbSession,
    period: Literal["day", "week"] = "day",
    date_: date = Query(alias="date", description="Start date, YYYY-MM-DD (UTC)"),
) -> DisaggregationOut:
    owned = await db.scalar(
        select(House.id).where(House.id == house_id, House.owner_id == user.id)
    )
    if owned is None:
        raise HTTPException(404, "House not found")
    return await get_disaggregation(db, house_id, period, date_)