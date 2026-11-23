from typing import Annotated

from fastapi import APIRouter, Header

from app.dependencies import DbSession

from ..schemas import DemoHome, DemoSessionIn, DemoTokens
from ..services import demo  # not re-exported by services: it imports home.api (cycle)

# Public on purpose (demo system): anyone may sign in as a demo home's owner, through the dashboard.
router = APIRouter(prefix="/demo", tags=["demo"])


@router.get("/homes", summary="Demo homes to sign in as (no token)")
async def list_demo_homes(db: DbSession) -> list[DemoHome]:
    return await demo.demo_homes(db)


@router.post("/session", summary="Sign in as a demo home's owner (no token)")
async def create_demo_session(
    body: DemoSessionIn,
    db: DbSession,
    # The dashboard's client secret, and the address of the visitor it signs in.
    x_demo_secret: Annotated[str, Header()] = "",
    x_demo_visitor: Annotated[str, Header(max_length=64)] = "",
) -> DemoTokens:
    return await demo.demo_session(db, body.house, secret=x_demo_secret, visitor=x_demo_visitor)
