from fastapi import APIRouter

from app.common.exceptions import NotFoundError
from app.dependencies import DbSession
from app.modules.energy.api import CurrentHome

from .. import services
from ..schemas import CurrentBill, Forecast, PastBill

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


@router.get(
    "/history", summary="Bills of the ended cycles, oldest first (the insight worker stores them)"
)
async def history(home_id: CurrentHome, db: DbSession) -> list[PastBill]:
    return [
        PastBill(
            period_start=b.period_start,
            period_end=b.period_end,
            kwh=b.kwh_total,
            amount=b.amount_total,
            coverage=b.coverage,
            tariff_straddle=b.tariff_straddle,
        )
        for b in await services.bill_history(db, home_id)
    ]


@router.get("/forecast", summary="The running cycle's bill at its end, from the weekday pattern")
async def forecast(home_id: CurrentHome, db: DbSession) -> Forecast:
    try:
        f = await services.forecast_bill(db, home_id)
    except LookupError as exc:  # no tariff plan, or no version valid for the cycle
        raise NotFoundError(str(exc), code="tariff_not_found") from None
    if f is None:
        raise NotFoundError(
            "Not enough full days of readings to forecast yet", code="forecast_unavailable"
        )
    return Forecast.model_validate(f)
