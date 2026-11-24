from fastapi import APIRouter

from app.dependencies import DbSession
from app.modules.home.api import HomeRead

from ..dependencies import CurrentUser
from ..schemas import DemoHome
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
