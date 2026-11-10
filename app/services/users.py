from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import User


class EmailTakenError(Exception):
    """The token's email already belongs to a local user with another Keycloak id."""


async def provision_user(db: AsyncSession, claims: dict[str, Any]) -> User:
    """Create or find the local profile by its external Keycloak subject."""
    keycloak_sub = claims["sub"]
    if not isinstance(keycloak_sub, str) or not keycloak_sub:
        raise ValueError("Keycloak sub must be a non-empty string")
    user = await db.scalar(select(User).where(User.keycloak_sub == keycloak_sub))
    if user is not None:
        return user
    email = claims.get("email")
    if not email:
        raise KeyError("email")
    user = User(keycloak_sub=keycloak_sub, email=email.lower(), full_name=claims.get("name"))
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        # Lost a race with the same user's concurrent first request, or the email is taken.
        existing = await db.scalar(select(User).where(User.keycloak_sub == keycloak_sub))
        if existing is None:
            raise EmailTakenError from None
        return existing
    return user
