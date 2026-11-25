from fastapi import APIRouter

from app.dependencies import DbSession

from .. import services
from ..dependencies import AdminUser, Claims, CurrentUser
from ..schemas import Me, Preferences, PreferencesUpdate, UserRead
from ..services import account  # not re-exported by services: it imports home.api (cycle)

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", summary="Current user")
async def read_me(user: CurrentUser, claims: Claims) -> Me:
    return Me(**UserRead.model_validate(user).model_dump(), roles=services.realm_roles(claims))


@router.get("/me/preferences", summary="The account's display and notification choices")
async def read_my_preferences(user: CurrentUser, db: DbSession) -> Preferences:
    return await services.read_preferences(db, user.id)


@router.patch("/me/preferences", summary="Change the account's display and notification choices")
async def update_my_preferences(
    patch: PreferencesUpdate, user: CurrentUser, db: DbSession
) -> Preferences:
    return await services.update_preferences(db, user.id, patch)


@router.delete(
    "/me",
    status_code=204,
    summary="Delete the account, and its home with all readings when its owner is the only member",
)
async def delete_me(user: CurrentUser, db: DbSession) -> None:
    await account.delete_account(db, user)


@router.get("", summary="List users (admin)")
async def list_users(_: AdminUser, db: DbSession, limit: int = 100) -> list[UserRead]:
    return [UserRead.model_validate(u) for u in await services.list_users(db, limit)]
