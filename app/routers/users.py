from fastapi import APIRouter
from sqlalchemy import select

from ..dependencies import AdminUser, Claims, CurrentUser, DbSession
from ..models import User
from ..schemas import Me, UserRead
from ..security import realm_roles

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", summary="Current user")
async def read_me(user: CurrentUser, claims: Claims) -> Me:
    return Me(**UserRead.model_validate(user).model_dump(), roles=realm_roles(claims))


@router.get("", summary="List users (admin)")
async def list_users(_: AdminUser, db: DbSession, limit: int = 100) -> list[UserRead]:
    rows = await db.scalars(select(User).order_by(User.created_at).limit(min(limit, 500)))
    return [UserRead.model_validate(u) for u in rows]
