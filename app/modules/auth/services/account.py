import logging

import httpx
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.modules.energy.api import erase_home_readings
from app.modules.home.api import Home, HomeInvite, HomeMember, Meter

from ..models import User
from ..utils.exceptions import (
    AccountDeleteUnavailableError,
    DemoUnavailableError,
    HomeHasMembersError,
)
from . import demo

log = logging.getLogger(__name__)


async def delete_account(db: AsyncSession, user: User) -> None:
    """Erases the caller's account: profile and what hangs on it, the home too when they are its
    only member (with its readings and aggregates), and the Keycloak account last.

    Local data goes first: a refused Keycloak delete then leaves a signed-in account with nothing in
    it, and the same call can be repeated; the other order would leave personal data behind an
    account that can no longer sign in to ask again.
    """
    if not settings.demo_admin_client_secret:  # checked before anything is erased
        raise AccountDeleteUnavailableError()
    member = await db.scalar(select(HomeMember).where(HomeMember.user_id == user.id))
    if member is not None and member.role == "owner":
        others = await db.scalar(
            select(func.count())
            .select_from(HomeMember)
            .where(HomeMember.home_id == member.home_id, HomeMember.user_id != user.id)
        )
        if others:
            raise HomeHasMembersError()
        await erase_home_readings(db, member.home_id)
        # The hardware outlives the household: it goes back to nobody (the invites cascade).
        await db.execute(update(Meter).where(Meter.home_id == member.home_id).values(home_id=None))
        await db.execute(delete(Home).where(Home.id == member.home_id))
    # An invite this account used stays as a record, with nobody on it.
    await db.execute(update(HomeInvite).where(HomeInvite.used_by == user.id).values(used_by=None))
    sub = user.keycloak_sub
    await db.execute(delete(User).where(User.id == user.id))
    await db.commit()
    if sub:
        try:
            async with httpx.AsyncClient(transport=demo._transport, timeout=10) as client:
                kc = demo._Keycloak(client)
                await kc.login()
                if not await kc.delete(sub):
                    raise AccountDeleteUnavailableError()
        except (httpx.HTTPError, DemoUnavailableError) as e:
            log.warning("account delete: Keycloak failed: %s", e)
            raise AccountDeleteUnavailableError() from e
