import uuid
from datetime import date

from fastapi import APIRouter

from app.dependencies import DbSession
from app.modules.auth.api import CurrentUser

from .. import services
from ..dependencies import Membership, WritableMembership
from ..schemas import (
    HomeRead,
    HomeUpdate,
    Invite,
    InviteAccept,
    MemberRead,
    MemberUpdate,
    PrivacyOverview,
    Province,
)

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


@router.post("/current/invites", status_code=201, summary="A one-time code to invite someone")
async def invite(member: Membership, db: DbSession) -> Invite:
    return await services.create_invite(db, member)


@router.post("/invites/accept", summary="Join a home with its code (seeing days only at first)")
async def accept(body: InviteAccept, user: CurrentUser, db: DbSession) -> HomeRead:
    return await services.read_home(db, await services.accept_invite(db, user.id, body.code))


@router.get("/current/members", summary="The household; addresses to the owner only")
async def members(member: Membership, db: DbSession) -> list[MemberRead]:
    return await services.list_members(db, member)


@router.patch(
    "/current/members/{user_id}", status_code=204, summary="How fine a member may see (owner)"
)
async def set_member(
    user_id: uuid.UUID, body: MemberUpdate, member: Membership, db: DbSession
) -> None:
    await services.set_member_detail(db, member, user_id, body.detail)


@router.delete("/current/members/{user_id}", status_code=204, summary="Remove a member (owner)")
async def remove(user_id: uuid.UUID, member: Membership, db: DbSession) -> None:
    await services.remove_member(db, member, user_id)


@router.delete("/current/membership", status_code=204, summary="Leave the home (a member)")
async def leave(member: Membership, db: DbSession) -> None:
    await services.leave(db, member)


@router.get("/provinces", summary="Province-level units a home can be in")
async def list_provinces(db: DbSession) -> list[Province]:
    return [Province.model_validate(p) for p in await services.provinces(db)]
