import uuid
from typing import Annotated

from fastapi import Depends

from app.modules.home.api import Membership


async def get_current_home(member: Membership) -> uuid.UUID:
    return member.home_id


CurrentHome = Annotated[uuid.UUID, Depends(get_current_home)]
