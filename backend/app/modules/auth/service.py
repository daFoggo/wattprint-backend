import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import (
    DUMMY_HASH,
    create_access_token,
    hash_password,
    hash_token,
    new_refresh_token,
    verify_password,
)
from app.modules.auth.models import RefreshToken
from app.modules.auth.schemas import TokenPair
from app.modules.users.models import User
from app.modules.users.schemas import UserCreate


def _now() -> datetime:
    return datetime.now(UTC)


async def register_user(db: AsyncSession, data: UserCreate) -> User | None:
    """Create a user, or return None if the email is already taken."""
    email = data.email.lower()
    if await db.scalar(select(User.id).where(User.email == email)):
        return None
    user = User(
        email=email, hashed_password=hash_password(data.password), full_name=data.full_name
    )
    db.add(user)
    await db.commit()
    return user


async def authenticate(db: AsyncSession, email: str, password: str) -> User | None:
    user = await db.scalar(select(User).where(User.email == email.lower()))
    if user is None or user.hashed_password is None:
        verify_password(password, DUMMY_HASH)
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


async def issue_tokens(db: AsyncSession, user: User) -> TokenPair:
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
    stored = await db.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw))
    )
    if stored is None:
        return None
    if stored.revoked_at is not None:
        # A rotated token came back: treat as theft and end every session of this user.
        await _revoke_all(db, stored.user_id)
        return None
    if stored.expires_at <= _now():
        return None
    user = await db.get(User, stored.user_id)
    if user is None or not user.is_active:
        return None
    stored.revoked_at = _now()
    return await issue_tokens(db, user)


async def revoke_refresh_token(db: AsyncSession, raw: str) -> None:
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.token_hash == hash_token(raw), RefreshToken.revoked_at.is_(None))
        .values(revoked_at=_now())
    )
    await db.commit()
