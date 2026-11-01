from fastapi import APIRouter

from app.api.deps import CurrentUser
from app.modules.users.schemas import UserRead

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", summary="Current user")
async def read_me(user: CurrentUser) -> UserRead:
    return UserRead.model_validate(user)
