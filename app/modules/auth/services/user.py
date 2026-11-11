from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import User
from ..repositories import UserRepository
from ..utils.exceptions import EmailTakenError


async def provision_user(db: AsyncSession, claims: dict[str, Any]) -> User:
    """Create or find the local profile by its external Keycloak subject."""
    keycloak_sub = claims["sub"]
    if not isinstance(keycloak_sub, str) or not keycloak_sub:
        raise ValueError("Keycloak sub must be a non-empty string")
    users = UserRepository(db)
    user = await users.read_by_keycloak_sub(keycloak_sub)
    if user is not None:
        return user
    email = claims.get("email")
    if not email:
        raise KeyError("email")
    try:
        user = await users.create(
            keycloak_sub=keycloak_sub, email=email.lower(), full_name=claims.get("name")
        )
        await db.commit()
    except IntegrityError:
        await db.rollback()
        # Lost a race with the same user's concurrent first request, or the email is taken.
        existing = await users.read_by_keycloak_sub(keycloak_sub)
        if existing is None:
            raise EmailTakenError from None
        return existing
    return user


async def list_users(db: AsyncSession, limit: int = 100) -> list[User]:
    return await UserRepository(db).read_many(order_by=[User.created_at], limit=limit)
