import hmac
import logging
import secrets
import time
from collections import defaultdict, deque
from datetime import timedelta

import httpx
import jwt
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.common.base_model import utcnow
from app.common.demo import GUEST_DOMAIN, demo_home_entries
from app.config import settings
from app.modules.home.api import HomeInvite, HomeMember, HomeRead, read_home

from ..models import User
from ..schemas.schema_demo import DemoDevice, DemoHome, DemoTokens
from ..utils.exceptions import (
    DemoForbiddenError,
    DemoFullError,
    DemoHomeNotFoundError,
    DemoNotForMembersError,
    DemoRateLimitedError,
    DemoUnavailableError,
)
from .token import decode_access_token
from .user import provision_user

log = logging.getLogger(__name__)

# The dashboard verifies `azp` against its own client and refreshes with that client's secret.
CLIENT_ID = "wattprint-web"
ADMIN_CLIENT_ID = "wattprint-demo-admin"
_transport: httpx.AsyncBaseTransport | None = None  # tests put a MockTransport here

# Every guest is a real Keycloak account: they live a day, at most GUESTS_MAX at once, and are made
# at most GUESTS_PER_MINUTE a minute (GUESTS_PER_VISITOR per address the dashboard names).
# shortcut: the per-minute windows count per API process (N workers allow N times as much); move
# them to the database or Redis when the API runs several workers.
GUEST_TTL = timedelta(hours=24)
GUESTS_MAX = 500
GUESTS_PER_MINUTE = 20
GUESTS_PER_VISITOR = 5
PURGE_BATCH = 50
_ALL = ""  # the global window's key; a visitor's key is their address
_sessions: defaultdict[str, deque[float]] = defaultdict(deque)


def _quota(visitor: str) -> None:
    now = time.monotonic()
    for key in [k for k, q in _sessions.items() if k != _ALL and (not q or now - q[-1] > 60)]:
        del _sessions[key]  # visitors idle for a minute: keeps the map as small as the traffic
    windows = [(_ALL, GUESTS_PER_MINUTE)]
    if visitor:  # unknown address (no proxy headers): only the global cap applies
        windows.append((visitor, GUESTS_PER_VISITOR))
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
    homes = demo_home_entries()
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


async def view_demo_home(db: AsyncSession, user: User, key: str) -> HomeRead:
    """Makes the account a read-only viewer of that demo home (moving its one viewer row there)."""
    email = next((e for home, e in await _homes(db) if home.key == key), None)
    if email is None:
        raise DemoHomeNotFoundError()
    home_id = await db.scalar(
        select(HomeMember.home_id)
        .join(User, User.id == HomeMember.user_id)
        .where(User.email == email, HomeMember.role == "owner")
    )
    if home_id is None:
        raise DemoHomeNotFoundError()
    # One statement, so two tabs cannot both insert: a viewer row moves, a member row stays.
    moved = await db.execute(
        insert(HomeMember)
        .values(home_id=home_id, user_id=user.id, role="viewer")
        .on_conflict_do_update(
            index_elements=[HomeMember.user_id],
            set_={"home_id": home_id},
            where=HomeMember.role == "viewer",
        )
        .returning(HomeMember.home_id)
    )
    if moved.scalar() is None:
        raise DemoNotForMembersError()
    await db.commit()
    member = HomeMember(home_id=home_id, user_id=user.id, role="viewer", detail="full")
    return await read_home(db, member)


def _is_guest():
    return User.email.like(f"%@{GUEST_DOMAIN}")


class _Keycloak:
    """The realm's admin API as the service account, plus the web client's password grant."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client
        self.users = (
            settings.token_url.split("/protocol/")[0].replace("/realms/", "/admin/realms/", 1)
            + "/users"
        )
        self.auth: dict[str, str] = {}

    async def login(self) -> None:
        r = await self.client.post(
            settings.token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": ADMIN_CLIENT_ID,
                "client_secret": settings.demo_admin_client_secret,
            },
        )
        if r.status_code != 200:
            log.warning("demo guest: admin client refused (%s)", r.status_code)
            raise DemoUnavailableError()
        self.auth = {"Authorization": f"Bearer {r.json()['access_token']}"}

    async def create(self, email: str, password: str) -> str:
        r = await self.client.post(
            self.users,
            headers=self.auth,
            json={
                "username": email,
                "email": email,
                "firstName": "Khách",
                "lastName": "demo",
                "enabled": True,
                "emailVerified": True,
                "credentials": [{"type": "password", "value": password, "temporary": False}],
            },
        )
        if r.status_code != 201:
            # Status only: Keycloak's error body can echo the username, an e-mail (D9-5).
            log.warning("demo guest: user not created (%s)", r.status_code)
            raise DemoUnavailableError()
        return r.headers["Location"].rsplit("/", 1)[-1]

    async def delete(self, sub: str) -> bool:
        r = await self.client.delete(f"{self.users}/{sub}", headers=self.auth)
        if r.status_code in (204, 404):  # 404: already gone
            return True
        # Left in place, expired guests would fill the cap unseen.
        log.warning("demo guest: Keycloak refused deleting %s (%s)", sub, r.status_code)
        return False

    async def grant(self, email: str, password: str) -> DemoTokens:
        r = await self.client.post(
            settings.token_url,
            data={
                "grant_type": "password",
                "client_id": CLIENT_ID,
                "client_secret": settings.wattprint_web_client_secret,
                "username": email,
                "password": password,
                "scope": "openid profile email roles",
            },
        )
        if r.status_code != 200:
            log.warning("demo guest: grant refused (%s)", r.status_code)
            raise DemoUnavailableError()
        return DemoTokens.model_validate(r.json())


async def _purge(db: AsyncSession, kc: _Keycloak) -> None:
    """Deletes guests older than a day: Keycloak account, then profile (cascades its data)."""
    old = (
        await db.execute(
            select(User.id, User.keycloak_sub)
            .where(_is_guest(), User.created_at < utcnow() - GUEST_TTL)
            .limit(PURGE_BATCH)
        )
    ).all()
    gone = [uid for uid, sub in old if sub is None or await kc.delete(sub)]
    if gone:
        # An invite a guest used (none can now) stays as a record, with nobody on it.
        await db.execute(
            update(HomeInvite).where(HomeInvite.used_by.in_(gone)).values(used_by=None)
        )
        await db.execute(delete(User).where(User.id.in_(gone)))
        await db.commit()


async def create_guest(db: AsyncSession, key: str, *, secret: str, visitor: str) -> DemoTokens:
    """A new guest account, viewer of that demo home, signed in for the dashboard (its tokens)."""
    if not settings.wattprint_web_client_secret or not settings.demo_admin_client_secret:
        raise DemoUnavailableError()
    if not hmac.compare_digest(secret.encode(), settings.wattprint_web_client_secret.encode()):
        raise DemoForbiddenError()
    if not any(home.key == key for home, _ in await _homes(db)):
        raise DemoHomeNotFoundError()
    _quota(visitor)
    email = f"guest-{secrets.token_hex(6)}@{GUEST_DOMAIN}"
    # Never stored or returned: the account is only ever used through the tokens below.
    password = secrets.token_urlsafe(24) + "Aa1!"
    try:
        async with httpx.AsyncClient(transport=_transport, timeout=10) as client:
            kc = _Keycloak(client)
            await kc.login()
            await _purge(db, kc)
            active = await db.scalar(select(func.count()).select_from(User).where(_is_guest()))
            if active >= GUESTS_MAX:
                raise DemoFullError()
            sub = await kc.create(email, password)
            try:
                tokens = await kc.grant(email, password)
                claims = await run_in_threadpool(decode_access_token, tokens.access_token)
                user = await provision_user(db, claims)
                await view_demo_home(db, user, key)
            except BaseException:
                await kc.delete(sub)  # no account left behind that nobody can sign in to
                raise
    except (httpx.HTTPError, jwt.PyJWTError) as e:  # Keycloak down, or its token or keys refused
        log.warning("demo guest: Keycloak failed: %s", e)
        raise DemoUnavailableError() from e
    return tokens
