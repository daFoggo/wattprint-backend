import uuid

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import User
from ..services.disaggregation import home_of


async def require_home(db: AsyncSession, user: User) -> uuid.UUID:
    """The home of the signed-in account, or 404 when it has none yet."""
    home_id = await home_of(db, user.id)
    if home_id is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "This account has no home yet: start a replay with POST /api/v1/simulations",
        )
    return home_id
