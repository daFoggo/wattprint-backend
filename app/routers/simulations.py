from fastapi import APIRouter, HTTPException, status

from ..dependencies import CurrentUser, DbSession
from ..schemas.disaggregation import DisaggregationOut
from ..schemas.simulation import SimulationCreate, SimulationOut
from ..services import disaggregation, simulation
from .common import require_home

router = APIRouter(prefix="/simulations", tags=["simulations"])

_NOT_FOUND = "Simulation not found"


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Replay one REFIT day through the NILM model, minute by minute",
)
async def start_simulation(
    body: SimulationCreate, user: CurrentUser, db: DbSession
) -> SimulationOut:
    """Starts a background replay and returns at once.

    The REFIT home of the signed-in account is created on first use. Every minute of the chosen
    day is read from the CSV, stored (aggregate and plug sub-meters), run through NILMFormer
    and stored again (per-appliance estimates). Poll `GET /simulations/{id}` for the progress and
    read `GET /simulations/{id}/result` or `GET /disaggregation/latest` for the results.
    Replaying the same stored day again replaces its previous data.
    """
    try:
        job = await simulation.start(db, user, body)
    except simulation.SimulationRefused as exc:
        raise HTTPException(exc.status, exc.detail) from None
    return simulation.job_out(job)


@router.get("/{simulation_id}", summary="Progress of a replay")
async def get_simulation(simulation_id: int, user: CurrentUser, db: DbSession) -> SimulationOut:
    home_id = await require_home(db, user)
    await simulation.reconcile(db, home_id)
    found = await simulation.find(db, home_id, simulation_id)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _NOT_FOUND)
    return found


@router.delete("/{simulation_id}", summary="Stop a running replay (stored data is kept)")
async def stop_simulation(simulation_id: int, user: CurrentUser, db: DbSession) -> SimulationOut:
    home_id = await require_home(db, user)
    await simulation.reconcile(db, home_id)
    simulation.cancel(home_id, simulation_id)
    found = await simulation.find(db, home_id, simulation_id)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _NOT_FOUND)
    return found


@router.get(
    "/{simulation_id}/result",
    response_model=DisaggregationOut,
    response_model_exclude_none=True,
    summary="Disaggregation of the replayed day (partial while it is running)",
)
async def simulation_result(
    simulation_id: int, user: CurrentUser, db: DbSession
) -> DisaggregationOut:
    home_id = await require_home(db, user)
    await simulation.reconcile(db, home_id)
    found = await simulation.find(db, home_id, simulation_id)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _NOT_FOUND)
    return await disaggregation.report(db, home_id, "day", found.replay_date)
