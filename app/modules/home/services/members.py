import hashlib
import secrets
import time
import uuid
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.api import User

from ..models import HomeInvite, HomeMember
from ..schemas import Invite, MemberRead
from ..utils import (
    AlreadyHasHomeError,
    DemoHomeReadOnlyError,
    HomeOwnerRequiredError,
    HomeReadOnlyError,
    InviteInvalidError,
    InviteRateLimitedError,
    MemberNotFoundError,
)
from .home import _is_demo_home

ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I/L: it is read out and typed
CODE_LENGTH = 10
VALID = timedelta(days=7)
TRIES, TRY_WINDOW_S = 10, 900
# shortcut: counted per API process; move to the database when the API runs several workers.
_tries: dict[uuid.UUID, deque[float]] = defaultdict(deque)


def _hash(code: str) -> str:
    return hashlib.sha256(code.strip().upper().encode()).hexdigest()


def _owner(member: HomeMember) -> None:
    if member.role != "owner":
        raise HomeOwnerRequiredError


async def create_invite(db: AsyncSession, member: HomeMember) -> Invite:
    _owner(member)
    if await _is_demo_home(db, member.home_id):
        raise DemoHomeReadOnlyError("A demo home takes no members")
    code = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))
    expires = datetime.now(UTC) + VALID
    db.add(HomeInvite(home_id=member.home_id, code_hash=_hash(code), expires_at=expires))
    await db.commit()
    return Invite(code=code, expires_at=expires)


async def accept_invite(db: AsyncSession, user_id: uuid.UUID, code: str) -> HomeMember:
    """The account joins the code's home, seeing days only. A demo visit gives way to it."""
    now = time.monotonic()
    tries = _tries[user_id]
    while tries and now - tries[0] > TRY_WINDOW_S:
        tries.popleft()
    if len(tries) >= TRIES:
        raise InviteRateLimitedError(headers={"Retry-After": str(TRY_WINDOW_S)})
    tries.append(now)
    # One statement, so a code is used once even when two accounts send it together.
    home_id = await db.scalar(
        update(HomeInvite)
        .where(
            HomeInvite.code_hash == _hash(code),
            HomeInvite.used_at.is_(None),
            HomeInvite.expires_at > datetime.now(UTC),
        )
        .values(used_by=user_id, used_at=datetime.now(UTC))
        .returning(HomeInvite.home_id)
    )
    if home_id is None:
        raise InviteInvalidError
    values = {"home_id": home_id, "role": "member", "detail": "daily"}
    joined = await db.scalar(
        insert(HomeMember)
        .values(user_id=user_id, **values)
        .on_conflict_do_update(
            index_elements=[HomeMember.user_id],
            set_=values,
            where=HomeMember.role == "viewer",
        )
        .returning(HomeMember.user_id)
    )
    if joined is None:
        await db.rollback()  # the code stays unused
        raise AlreadyHasHomeError
    await db.commit()
    return await db.get(HomeMember, (home_id, user_id), populate_existing=True)


async def list_members(db: AsyncSession, member: HomeMember) -> list[MemberRead]:
    """The household, owner first; demo visitors are not part of it. Addresses: the owner only."""
    if member.role == "viewer":
        raise HomeReadOnlyError
    rows = await db.execute(
        select(HomeMember, User.full_name, User.email)
        .join(User, User.id == HomeMember.user_id)
        .where(HomeMember.home_id == member.home_id, HomeMember.role != "viewer")
        .order_by(HomeMember.role != "owner", HomeMember.joined_at)
    )
    return [
        MemberRead(
            user_id=m.user_id,
            name=name,
            email=email if member.role == "owner" else None,
            role=m.role,
            detail=m.detail,
        )
        for m, name, email in rows
    ]


async def _member_of(db: AsyncSession, home_id: uuid.UUID, user_id: uuid.UUID) -> HomeMember:
    found = await db.get(HomeMember, (home_id, user_id))
    if found is None or found.role != "member":
        raise MemberNotFoundError
    return found


async def set_member_detail(
    db: AsyncSession, member: HomeMember, user_id: uuid.UUID, detail: str
) -> None:
    _owner(member)
    other = await _member_of(db, member.home_id, user_id)
    other.detail = detail
    if detail == "daily":
        # Lazy: insight reads homes through home.api, so a top-level import is a cycle.
        from app.modules.insight.api import forget_fine_watches

        await forget_fine_watches(db, user_id, member.home_id)
    await db.commit()


async def _remove(db: AsyncSession, home_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """The membership and what the person made of this home: nothing keeps sending it to them."""
    from app.modules.copilot.api import delete_all_conversations  # lazy: see set_member_detail
    from app.modules.insight.api import forget_member

    await forget_member(db, user_id, home_id)
    await db.execute(
        delete(HomeMember).where(HomeMember.home_id == home_id, HomeMember.user_id == user_id)
    )
    await delete_all_conversations(db, user_id, home_id)  # commits


async def remove_member(db: AsyncSession, member: HomeMember, user_id: uuid.UUID) -> None:
    _owner(member)
    await _member_of(db, member.home_id, user_id)
    await _remove(db, member.home_id, user_id)


async def leave(db: AsyncSession, member: HomeMember) -> None:
    if member.role != "member":  # an owner deletes the account instead; a visitor just moves on
        raise HomeReadOnlyError("Only a member can leave a home")
    await _remove(db, member.home_id, member.user_id)
