"""Demo sign-in: the seeded homes of scripts/demo_homes.toml, and a session as a home's owner."""

import hmac
import logging
import time
import tomllib
from collections import defaultdict, deque
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.modules.home.api import HomeMember

from ..models import User
from ..schemas.schema_demo import DemoDevice, DemoHome, DemoTokens
from ..utils.exceptions import (
    DemoForbiddenError,
    DemoHomeNotFoundError,
    DemoRateLimitedError,
    DemoUnavailableError,
)

log = logging.getLogger(__name__)

# The dashboard verifies `azp` against its own client and refreshes with that client's secret.
CLIENT_ID = "wattprint-web"
_transport: httpx.AsyncBaseTransport | None = None  # tests put a MockTransport here
ADMIN_CLIENT_ID = "wattprint-demo-admin"
# Each grant is a real Keycloak session kept for weeks. Only the dashboard may ask (it sends its
# client secret) and it names the visitor's address: a cap per visitor, a global one as backstop.
# shortcut: counted per API process (N workers allow N times as much); move it to the database or
# Redis when the API runs several workers.
SESSIONS_PER_MINUTE = 20
SESSIONS_PER_VISITOR = 5
_ALL = ""  # the global window's key; a visitor's key is their address
_sessions: defaultdict[str, deque[float]] = defaultdict(deque)


def _quota(visitor: str) -> None:
    now = time.monotonic()
    for key in [k for k, q in _sessions.items() if k != _ALL and (not q or now - q[-1] > 60)]:
        del _sessions[key]  # visitors idle for a minute: keeps the map as small as the traffic
    windows = [(_ALL, SESSIONS_PER_MINUTE)]
    if visitor:  # unknown address (no proxy headers): only the global cap applies
        windows.append((visitor, SESSIONS_PER_VISITOR))
    for key, cap in windows:
        q = _sessions[key]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= cap:
            raise DemoRateLimitedError(headers={"Retry-After": "60"})
    for key, _ in windows:
        _sessions[key].append(now)


async def _homes(db: AsyncSession) -> list[tuple[DemoHome, str]]:
    """(home, owner email) for each toml home whose owner is a member of a home."""
    homes = tomllib.loads(Path(settings.demo_homes_file).read_text())["home"]
    emails = [h["owner"]["email"].lower() for h in homes]
    seeded = set(
        await db.scalars(
            select(User.email)
            .join(HomeMember, HomeMember.user_id == User.id)
            .where(User.email.in_(emails))
        )
    )
    return [
        (
            DemoHome(
                key=str(h.get("key", h["house"])),
                house=h["house"],
                name=h.get("name", f"REFIT House {h['house']}"),
                devices=[
                    DemoDevice(label=label, name=name)
                    for label, name in h["devices"].items()
                    if label != "Other"
                ],
            ),
            email,
        )
        for h, email in zip(homes, emails, strict=True)
        if email in seeded
    ]


async def demo_homes(db: AsyncSession) -> list[DemoHome]:
    return [home for home, _ in await _homes(db)]


async def demo_session(db: AsyncSession, key: str, *, secret: str, visitor: str) -> DemoTokens:
    if not settings.demo_password or not settings.wattprint_web_client_secret:
        raise DemoUnavailableError()
    if not hmac.compare_digest(secret.encode(), settings.wattprint_web_client_secret.encode()):
        raise DemoForbiddenError()
    email = next((e for home, e in await _homes(db) if home.key == key), None)
    if email is None:
        raise DemoHomeNotFoundError()
    _quota(visitor)
    form = {
        "grant_type": "password",
        "client_id": CLIENT_ID,
        "client_secret": settings.wattprint_web_client_secret,
        "username": email,
        "password": settings.demo_password,
        "scope": "openid profile email roles",
    }
    try:
        async with httpx.AsyncClient(transport=_transport, timeout=10) as client:
            r = await client.post(settings.token_url, data=form)
            # Keycloak answers a locked account like a wrong password; anyone typing a wrong
            # password for the shared owner locks it, so clear the lockout once and try again.
            if r.status_code != 200 and await _unlock(client, email):
                r = await client.post(settings.token_url, data=form)
    except httpx.HTTPError as e:
        log.warning("demo sign-in: Keycloak unreachable: %s", e)
        raise DemoUnavailableError() from e
    if r.status_code != 200:
        log.warning("demo sign-in for %s refused (%s): %s", key, r.status_code, r.text[:300])
        raise DemoUnavailableError()
    return DemoTokens.model_validate(r.json())


async def _unlock(client: httpx.AsyncClient, email: str) -> bool:
    """Clears the brute-force lockout of the user with this email; False when it could not."""
    if not settings.demo_admin_client_secret:
        return False
    admin = settings.token_url.split("/protocol/")[0].replace("/realms/", "/admin/realms/", 1)
    r = await client.post(
        settings.token_url,
        data={
            "grant_type": "client_credentials",
            "client_id": ADMIN_CLIENT_ID,
            "client_secret": settings.demo_admin_client_secret,
        },
    )
    if r.status_code != 200:
        log.warning("demo unlock: admin client refused (%s)", r.status_code)
        return False
    auth = {"Authorization": f"Bearer {r.json()['access_token']}"}
    r = await client.get(f"{admin}/users", params={"email": email, "exact": "true"}, headers=auth)
    users = r.json() if r.status_code == 200 else []
    if len(users) != 1:
        log.warning("demo unlock: owner not found (%s)", r.status_code)
        return False
    r = await client.delete(
        f"{admin}/attack-detection/brute-force/users/{users[0]['id']}", headers=auth
    )
    return r.status_code == 204
