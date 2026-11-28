from typing import Annotated

from fastapi import Depends
from sqlalchemy import select

from app.dependencies import DbSession
from app.modules.auth.api import CurrentUser

from .models import HomeMember
from .utils import DetailRestrictedError, HomeNotFoundError, HomeReadOnlyError


async def get_membership(user: CurrentUser, db: DbSession) -> HomeMember:
    # One row at most: uq_home_member_user_id allows a single home per user.
    member = await db.scalar(select(HomeMember).where(HomeMember.user_id == user.id))
    if member is None:
        raise HomeNotFoundError
    return member


Membership = Annotated[HomeMember, Depends(get_membership)]


async def get_writable_membership(member: Membership) -> HomeMember:
    """A membership that may change the home's shared state: a demo viewer only reads."""
    if member.role == "viewer":
        raise HomeReadOnlyError
    return member


WritableMembership = Annotated[HomeMember, Depends(get_writable_membership)]


async def get_detailed_membership(member: Membership) -> HomeMember:
    """A membership that may see figures finer than a day (R4.3)."""
    if member.detail == "daily":
        raise DetailRestrictedError
    return member


DetailedMembership = Annotated[HomeMember, Depends(get_detailed_membership)]
