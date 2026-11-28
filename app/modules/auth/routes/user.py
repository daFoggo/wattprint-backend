from fastapi import APIRouter

from app.common import outbound
from app.dependencies import DbSession

from .. import services
from ..dependencies import AdminUser, Claims, CurrentUser
from ..schemas import Me, Preferences, PreferencesUpdate, UserRead
from ..schemas.schema_consent import Consent, ConsentUpdate, OutboundRow, Purpose
from ..services import (
    account,  # not re-exported by services: it imports home.api (cycle)
    consent,
)

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


@router.get("/me/consents", summary="Consent per purpose: wappi, voice, email (off until agreed)")
async def read_my_consents(user: CurrentUser, db: DbSession) -> list[Consent]:
    return await consent.consents(db, user.id)


@router.put("/me/consents/{purpose}", summary="Agree or withdraw: each change is a new record")
async def set_my_consent(
    purpose: Purpose, body: ConsentUpdate, user: CurrentUser, db: DbSession
) -> Consent:
    return await consent.set_consent(db, user.id, purpose, body.granted)


@router.get("/me/outbound", summary="What was sent outside WattPrint in the last 30 days")
async def read_my_outbound(user: CurrentUser) -> list[OutboundRow]:
    return [OutboundRow(**r) for r in await outbound.recent(user.id)]


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
