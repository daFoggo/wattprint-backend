from fastapi import APIRouter

from app.common.exceptions import NotFoundError
from app.dependencies import DbSession
from app.modules.energy.api import CurrentHome

from .. import services
from ..schemas import Cohort

router = APIRouter()


@router.get("/cohort", summary="This home against similar homes over the last 30 whole days")
async def cohort(home_id: CurrentHome, db: DbSession) -> Cohort:
    view = await services.cohort_for(db, home_id)
    if view is None:
        raise NotFoundError("Fewer than 10 homes to compare with yet", code="cohort_too_small")
    return Cohort.model_validate(view)
