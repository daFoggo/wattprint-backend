from fastapi import APIRouter

from app.dependencies import DbSession

from .. import services
from ..dependencies import Membership
from ..schemas import HomeRead, HomeUpdate, Province

router = APIRouter()


@router.get("/current", summary="The account's home: profile and the account's role in it")
async def read_current_home(member: Membership, db: DbSession) -> HomeRead:
    return await services.read_home(db, member)


@router.patch("/current", summary="Change the home's profile (owner only)")
async def update_current_home(patch: HomeUpdate, member: Membership, db: DbSession) -> HomeRead:
    return await services.update_home(db, member, patch)


@router.get("/provinces", summary="Province-level units a home can be in")
async def list_provinces(db: DbSession) -> list[Province]:
    return [Province.model_validate(p) for p in await services.provinces(db)]
