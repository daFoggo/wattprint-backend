from datetime import date
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from app.api.deps import DbSession
from app.core.security import CurrentUser

from .models import House, SimulationJob
from .schemas import DisaggregationOut, LatestOut, SimulationCreate, SimulationOut
from .service import get_disaggregation, get_latest
from .simulation import fail_orphans, job_out, start_job

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

@router.get(
    "/{house_id}/latest",
    response_model=LatestOut,
    summary="Last N minutes: aggregate power + predicted watts per appliance",
)
async def latest(
    house_id: int,
    user: CurrentUser,
    db: DbSession,
    minutes: int = Query(30, ge=1, le=1440),
) -> LatestOut:
    owned = await db.scalar(
        select(House.id).where(House.id == house_id, House.owner_id == user.id)
    )
    if owned is None:
        raise HTTPException(404, "House not found")
    return await get_latest(db, house_id, minutes)

@router.post(
    "/{house_id}/simulations",
    response_model=SimulationOut,
    status_code=202,
    summary="Start replaying one REFIT day: read minute by minute, predict, store",
)
async def create_simulation(house_id: int, body: SimulationCreate, user: CurrentUser, db: DbSession):
    house = await db.get(House, house_id)
    if house is None:  # demo convenience: the caller claims an unused house id
        db.add(House(id=house_id, owner_id=user.id, name=f"REFIT simulated house {house_id}"))
        await db.flush()
    elif house.owner_id != user.id:
        raise HTTPException(404, "House not found")

    await fail_orphans(db)
    busy = await db.scalar(
        select(SimulationJob.id).where(
            SimulationJob.house_id == house_id, SimulationJob.status.in_(("pending", "running"))
        )
    )
    if busy is not None:
        raise HTTPException(409, f"Simulation {busy} is still running for this house")

    job = SimulationJob(
        house_id=house_id, owner_id=user.id, day=body.date,
        rows_per_second=body.rows_per_second, status="pending",
    )
    db.add(job)
    await db.commit()
    start_job(job.id)
    return job_out(job)


async def _owned_job(db, user, house_id: int, job_id: int) -> SimulationJob:
    await fail_orphans(db)
    job = await db.scalar(
        select(SimulationJob).where(
            SimulationJob.id == job_id, SimulationJob.house_id == house_id,
            SimulationJob.owner_id == user.id,
        )
    )
    if job is None:
        raise HTTPException(404, "Simulation not found")
    return job


@router.get("/{house_id}/simulations/{job_id}", response_model=SimulationOut,
            summary="Simulation status and progress")
async def get_simulation(house_id: int, job_id: int, user: CurrentUser, db: DbSession):
    return job_out(await _owned_job(db, user, house_id, job_id))


@router.get(
    "/{house_id}/simulations/{job_id}/result",
    response_model=DisaggregationOut,
    response_model_exclude_none=True,
    summary="Disaggregation result of the simulated day (partial while running)",
)
async def simulation_result(house_id: int, job_id: int, user: CurrentUser, db: DbSession):
    job = await _owned_job(db, user, house_id, job_id)
    return await get_disaggregation(db, house_id, "day", job.day)