import uuid
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import User


class EmailTakenError(Exception):
    """The token's email already belongs to a local user with another Keycloak id."""


async def provision_user(db: AsyncSession, claims: dict[str, Any]) -> User:
    """The local profile of a Keycloak user, created on first sight. users.id is the token `sub`."""
    user_id = uuid.UUID(claims["sub"])
    user = await db.get(User, user_id)
    if user is not None:
        return user
    email = claims.get("email")
    if not email:
        raise KeyError("email")
    user = User(id=user_id, email=email.lower(), full_name=claims.get("name"))
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        # Lost a race with the same user's concurrent first request, or the email is taken.
        existing = await db.get(User, user_id)
        if existing is None:
            raise EmailTakenError from None
        return existing
    return user
