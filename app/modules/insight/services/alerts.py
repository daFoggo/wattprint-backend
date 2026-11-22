import uuid

from sqlalchemy import case, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.home.api import Device

from ..models import Alert, AlertFeedback


async def list_alerts(
    session: AsyncSession, home_id: uuid.UUID, status: str | None, limit: int
) -> list[tuple[Alert, Device | None]]:
    """Unresolved first, then newest first."""
    q = (
        select(Alert, Device)
        .outerjoin(Device, Device.id == Alert.device_id)
        .where(Alert.home_id == home_id)
        .order_by(case((Alert.status == "resolved", 1), else_=0), Alert.ts.desc())
        .limit(limit)
    )
    if status:
        q = q.where(Alert.status == status)
    return [tuple(r) for r in await session.execute(q)]


async def acknowledge(session: AsyncSession, home_id: uuid.UUID, alert_id: uuid.UUID) -> bool:
    """Open → acknowledged; False when the home has no such alert. Idempotent."""
    found = await session.scalar(
        select(Alert.id).where(Alert.id == alert_id, Alert.home_id == home_id)
    )
    if found is None:
        return False
    await session.execute(
        update(Alert)
        .where(Alert.id == alert_id, Alert.status == "open")
        .values(status="acknowledged")
    )
    await session.commit()
    return True


async def verdicts(
    session: AsyncSession, user_id: uuid.UUID, alert_ids: list[uuid.UUID]
) -> dict[uuid.UUID, str]:
    """The user's own verdict on each of these alerts."""
    if not alert_ids:
        return {}
    rows = await session.execute(
        select(AlertFeedback.alert_id, AlertFeedback.verdict).where(
            AlertFeedback.user_id == user_id, AlertFeedback.alert_id.in_(alert_ids)
        )
    )
    return {a: v for a, v in rows}
