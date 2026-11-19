import uuid

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import UserPreference
from ..schemas import Preferences, PreferencesUpdate


async def read_preferences(db: AsyncSession, user_id: uuid.UUID) -> Preferences:
    """The stored choices, or the defaults for an account that never saved any."""
    row = await db.get(UserPreference, user_id)
    return Preferences.model_validate(row) if row else Preferences()


async def update_preferences(
    db: AsyncSession, user_id: uuid.UUID, patch: PreferencesUpdate
) -> Preferences:
    changes = {k: v for k, v in patch.model_dump(exclude_unset=True).items() if v is not None}
    if changes:
        values = {**Preferences().model_dump(), **changes, "user_id": user_id}
        stmt = insert(UserPreference).values(values)
        await db.execute(
            stmt.on_conflict_do_update(
                index_elements=[UserPreference.user_id],
                set_={**changes, "updated_at": func.now()},
            )
        )
        await db.commit()
    return await read_preferences(db, user_id)
