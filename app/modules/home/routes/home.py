from datetime import date

from fastapi import APIRouter

from app.dependencies import DbSession

from .. import services
from ..dependencies import Membership, WritableMembership
from ..schemas import HomeRead, HomeUpdate, PrivacyOverview, Province

router = APIRouter()


@router.get("/current", summary="The account's home: profile and the account's role in it")
async def read_current_home(member: Membership, db: DbSession) -> HomeRead:
    return await services.read_home(db, member)


@router.get("/current/privacy", summary="What is kept of the home's use, for how long, since when")
async def read_privacy(member: Membership, db: DbSession) -> PrivacyOverview:
    return await services.privacy_overview(db, member)


@router.patch("/current", summary="Change the home's profile (owner only)")
async def update_current_home(
    patch: HomeUpdate, member: WritableMembership, db: DbSession
) -> HomeRead:
    return await services.update_home(db, member, patch)


@router.delete(
    "/current/history",
    status_code=204,
    summary="Erase the home's history before a day (all without one): owner only, not for demos",
)
async def erase_my_history(
    member: WritableMembership, db: DbSession, before: date | None = None
) -> None:
    await services.erase_history(db, member, before)


@router.get("/provinces", summary="Province-level units a home can be in")
async def list_provinces(db: DbSession) -> list[Province]:
    return [Province.model_validate(p) for p in await services.provinces(db)]
