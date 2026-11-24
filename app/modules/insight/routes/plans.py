import uuid
from datetime import UTC, datetime

from fastapi import APIRouter

from app.common.exceptions import ConflictError, NotFoundError, UnprocessableError
from app.dependencies import DbSession
from app.modules.home.api import Membership

from .. import services
from ..models import SavingsPlan
from ..schemas import PlanBasis, PlanCreate, PlanHistoryItem, PlanRead
from ..utils import PlanError

router = APIRouter()


def _item(plan: SavingsPlan, user_id: uuid.UUID) -> PlanHistoryItem:
    return PlanHistoryItem(
        **_read(plan).model_dump(), stopped_at=plan.stopped_at, mine=plan.user_id == user_id
    )


def _read(plan: SavingsPlan) -> PlanRead:
    return PlanRead.model_validate(
        {
            **{c: getattr(plan, c) for c in PlanRead.model_fields if c != "days"},
            "days": [{"date": d, **v} for d, v in sorted(plan.days.items())],
        }
    )


# Any member, a demo viewer too: a plan is the person's own, it changes nothing of the home.
@router.post("/plans", status_code=201, summary="Start a savings plan for this billing cycle")
async def create(body: PlanCreate, member: Membership, db: DbSession) -> PlanRead:
    try:
        plan = await services.create_plan(
            db,
            member.user_id,
            member.home_id,
            start_on=body.start_on,
            actions=[a.model_dump() for a in body.actions],
            now=datetime.now(UTC),
        )
    except PlanError as e:
        error = ConflictError if e.code == "plan_exists" else UnprocessableError
        raise error(str(e), code=e.code) from e
    except LookupError as e:  # no tariff plan: nothing to price
        raise NotFoundError("This home has no tariff plan", code="tariff_not_found") from e
    await db.commit()
    return _read(plan)


@router.get("/plans/basis", summary="What a plan started now is measured against")
async def basis(member: Membership, db: DbSession) -> PlanBasis:
    try:
        b = await services.plan_basis(db, member.home_id, datetime.now(UTC))
    except PlanError as e:
        raise UnprocessableError(str(e), code=e.code) from e
    except LookupError as e:
        raise NotFoundError("This home has no tariff plan", code="tariff_not_found") from e
    return PlanBasis.model_validate(b, from_attributes=True)


@router.get("/plans/history", summary="The home's finished plans: the caller's and the owners'")
async def history(member: Membership, db: DbSession) -> list[PlanHistoryItem]:
    plans = await services.plan_history(db, member.user_id, member.home_id, datetime.now(UTC))
    return [_item(p, member.user_id) for p in plans]


@router.get("/plans/current", summary="The user's running savings plan with its frozen days")
async def current(member: Membership, db: DbSession) -> PlanRead:
    plan = await services.current_plan(db, member.user_id, member.home_id)
    if plan is None:
        raise NotFoundError("No running plan", code="plan_not_found")
    return _read(plan)


@router.delete("/plans/current", status_code=204, summary="Stop the running savings plan")
async def stop(member: Membership, db: DbSession) -> None:
    if not await services.stop_plan(db, member.user_id, member.home_id, datetime.now(UTC)):
        raise NotFoundError("No running plan", code="plan_not_found")
    await db.commit()


# After the fixed paths (`basis`, `history`, `current`), which would otherwise read as an id.
@router.get("/plans/{plan_id}", summary="One plan the caller may open: theirs or a home owner's")
async def one(plan_id: uuid.UUID, member: Membership, db: DbSession) -> PlanHistoryItem:
    plan = await services.visible_plan(db, member.user_id, member.home_id, plan_id)
    if plan is None:
        raise NotFoundError("No such plan", code="plan_not_found")
    return _item(plan, member.user_id)
