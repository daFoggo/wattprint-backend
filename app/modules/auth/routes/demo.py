from typing import Annotated

from fastapi import APIRouter, Header

from app.dependencies import DbSession
from app.modules.home.api import HomeRead

from ..dependencies import CurrentUser
from ..schemas import DemoHome, DemoTokens
from ..services import demo  # not re-exported by services: it imports home.api (cycle)

router = APIRouter(prefix="/demo", tags=["demo"])


# Public on purpose: the sign-in page shows them before anyone has an account.
@router.get("/homes", summary="Demo homes a signed-in account can view (no token)")
async def list_demo_homes(db: DbSession) -> list[DemoHome]:
    return await demo.demo_homes(db)


@router.post(
    "/homes/{key}/view",
    summary="View a demo home read-only from this account (not for members of a real home)",
)
async def view_demo_home(key: str, user: CurrentUser, db: DbSession) -> HomeRead:
    return await demo.view_demo_home(db, user, key)


# No token: the visitor has no account yet. Only the dashboard may ask (it sends its client secret)
# and it names the visitor's address for the per-visitor cap.
@router.post(
    "/homes/{key}/guest",
    summary="A new guest account viewing that demo home, signed in for the dashboard (its tokens)",
)
async def create_guest(
    key: str,
    db: DbSession,
    x_demo_secret: Annotated[str, Header()] = "",
    x_demo_visitor: Annotated[str, Header(max_length=64)] = "",
) -> DemoTokens:
    return await demo.create_guest(db, key, secret=x_demo_secret, visitor=x_demo_visitor)
