from typing import Annotated

from fastapi import Depends
from sqlalchemy import select

from app.dependencies import DbSession
from app.modules.auth.api import CurrentUser

from .models import HomeMember
from .utils import HomeNotFoundError


async def get_membership(user: CurrentUser, db: DbSession) -> HomeMember:
    # One row at most: uq_home_member_user_id allows a single home per user.
    member = await db.scalar(select(HomeMember).where(HomeMember.user_id == user.id))
    if member is None:
        raise HomeNotFoundError
    return member


Membership = Annotated[HomeMember, Depends(get_membership)]
