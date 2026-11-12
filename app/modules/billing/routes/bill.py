from fastapi import APIRouter

from app.common.exceptions import NotFoundError
from app.dependencies import DbSession
from app.modules.energy.api import CurrentHome

from .. import services
from ..schemas import CurrentBill

router = APIRouter()


@router.get(
    "/current", summary="The running billing cycle so far, priced by the tariff tiers; reads only"
)
async def current(home_id: CurrentHome, db: DbSession) -> CurrentBill:
    try:
        bill = await services.current_bill(db, home_id)
    except LookupError as exc:  # no tariff plan, or no version valid for the cycle
        raise NotFoundError(str(exc), code="tariff_not_found") from None
    return CurrentBill.model_validate(bill)
