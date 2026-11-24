import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Alert, AlertFeedback

WINDOW = timedelta(days=90)
STEP = 0.5  # each "not an anomaly" widens the band by half its width
MAX_FACTOR = 3.0


async def record_feedback(
    s: AsyncSession, home_id: uuid.UUID, user_id: uuid.UUID, alert_id: uuid.UUID, verdict: str
) -> bool:
    """Keep the member's verdict (a new one replaces theirs); False when the alert is not this
    home's."""
    kind = await s.scalar(select(Alert.kind).where(Alert.id == alert_id, Alert.home_id == home_id))
    if kind is None:
        return False
    stmt = insert(AlertFeedback).values(
        alert_id=alert_id, user_id=user_id, home_id=home_id, kind=kind, verdict=verdict
    )
    await s.execute(
        stmt.on_conflict_do_update(
            index_elements=["alert_id", "user_id"],
            set_={"verdict": stmt.excluded.verdict, "at": func.now()},
        )
    )
    return True


async def sensitivity(
    s: AsyncSession,
    home_id: uuid.UUID,
    kind: str,
    device_id: uuid.UUID | None = None,
    signal: str | None = None,
) -> float:
    """How far past its usual band an alert of this kind must go for the home (and, for a device
    anomaly, that device and signal): 1 = as learnt; each "not an anomaly" in the last 90 days
    adds half a band, at most three."""
    q = (
        select(func.count())
        .select_from(AlertFeedback)
        .where(
            AlertFeedback.home_id == home_id,
            AlertFeedback.kind == kind,
            AlertFeedback.verdict == "not_anomaly",
            AlertFeedback.at >= datetime.now(UTC) - WINDOW,
        )
    )
    if device_id is not None or signal is not None:
        q = q.join(Alert, Alert.id == AlertFeedback.alert_id)
    if device_id is not None:
        q = q.where(Alert.device_id == device_id)
    if signal is not None:
        q = q.where(Alert.payload["signal"].astext == signal)
    n = await s.scalar(q)
    return min(MAX_FACTOR, 1.0 + STEP * (n or 0))
