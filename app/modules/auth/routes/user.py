from fastapi import APIRouter

from app.dependencies import DbSession

from .. import services
from ..dependencies import AdminUser, Claims, CurrentUser
from ..schemas import Me, UserRead

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", summary="Current user")
async def read_me(user: CurrentUser, claims: Claims) -> Me:
    return Me(**UserRead.model_validate(user).model_dump(), roles=services.realm_roles(claims))


@router.get("", summary="List users (admin)")
async def list_users(_: AdminUser, db: DbSession, limit: int = 100) -> list[UserRead]:
    return [UserRead.model_validate(u) for u in await services.list_users(db, limit)]
