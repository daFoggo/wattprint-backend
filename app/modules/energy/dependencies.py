import uuid
from typing import Annotated

from fastapi import Depends

from app.modules.home.api import DetailedMembership, Membership


async def get_current_home(member: Membership) -> uuid.UUID:
    return member.home_id


CurrentHome = Annotated[uuid.UUID, Depends(get_current_home)]


async def get_detailed_home(member: DetailedMembership) -> uuid.UUID:
    return member.home_id


DetailedHome = Annotated[uuid.UUID, Depends(get_detailed_home)]
