import uuid
from typing import Annotated

from fastapi import Depends
from sqlalchemy import select

from app.dependencies import DbSession
from app.modules.auth.api import CurrentUser
from app.modules.home.api import HomeMember

from .utils import HomeNotFoundError


async def get_current_home(user: CurrentUser, db: DbSession) -> uuid.UUID:
    # One row at most: uq_home_member_user_id allows a single home per user.
    home_id = await db.scalar(select(HomeMember.home_id).where(HomeMember.user_id == user.id))
    if home_id is None:
        raise HomeNotFoundError
    return home_id


CurrentHome = Annotated[uuid.UUID, Depends(get_current_home)]
