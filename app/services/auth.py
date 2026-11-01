import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from ..config import settings
from ..models import RefreshToken, User
from ..schemas import TokenPair, UserCreate
from ..security import (
    DUMMY_HASH,
    create_access_token,
    hash_password,
    hash_token,
    new_refresh_token,
    verify_password,
)


def _now() -> datetime:
    return datetime.now(UTC)


async def register_user(db: AsyncSession, data: UserCreate) -> User | None:
    """Create a user, or return None if the email is already taken."""
    email = data.email.lower()
    # Hash before the lookup result is used so an existing email costs the same time.
    hashed = await run_in_threadpool(hash_password, data.password)
    if await db.scalar(select(User.id).where(User.email == email)):
        return None
    user = User(
        email=email,
        hashed_password=hashed,
        full_name=data.full_name,
    )
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        # Lost a race with a concurrent registration of the same email.
        await db.rollback()
        return None
    return user


async def authenticate(db: AsyncSession, email: str, password: str) -> User | None:
    user = await db.scalar(select(User).where(User.email == email.lower()))
    if user is None or user.hashed_password is None:
        await run_in_threadpool(verify_password, password, DUMMY_HASH)
        return None
    if not await run_in_threadpool(verify_password, password, user.hashed_password):
        return None
    return user


async def issue_tokens(db: AsyncSession, user: User) -> TokenPair:
    # Opportunistic cleanup: only this user's already-expired rows. Unexpired rows are kept even
    # when revoked, so replaying an old revoked token still triggers theft detection.
    await db.execute(
        delete(RefreshToken).where(
            RefreshToken.user_id == user.id, RefreshToken.expires_at < _now()
        )
    )
    raw, hashed = new_refresh_token()
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hashed,
            expires_at=_now() + timedelta(days=settings.refresh_token_expire_days),
        )
    )
    await db.commit()
    return TokenPair(access_token=create_access_token(str(user.id)), refresh_token=raw)


async def _revoke_all(db: AsyncSession, user_id: uuid.UUID) -> None:
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=_now())
    )
    await db.commit()


async def rotate_refresh_token(db: AsyncSession, raw: str) -> TokenPair | None:
    """Exchange a refresh token for a new pair. Each token is single-use."""
    token_hash = hash_token(raw)
    now = _now()
    # Atomic claim: only one concurrent caller can flip revoked_at from NULL.
    user_id = await db.scalar(
        update(RefreshToken)
        .where(
            RefreshToken.token_hash == token_hash,
            RefreshToken.revoked_at.is_(None),
            RefreshToken.expires_at > now,
        )
        .values(revoked_at=now)
        .returning(RefreshToken.user_id)
    )
    if user_id is None:
        await db.rollback()
        stored = await db.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
        if stored is not None and stored.revoked_at is not None:
            # Replay within the grace window is a benign retry/race: just reject it.
            # Older reuse of a revoked token is treated as theft: end every session.
            grace = timedelta(seconds=settings.refresh_reuse_grace_seconds)
            if now - stored.revoked_at > grace:
                await _revoke_all(db, stored.user_id)
        return None
    await db.commit()
    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        return None
    return await issue_tokens(db, user)


async def revoke_refresh_token(db: AsyncSession, raw: str) -> None:
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.token_hash == hash_token(raw), RefreshToken.revoked_at.is_(None))
        .values(revoked_at=_now())
    )
    await db.commit()
