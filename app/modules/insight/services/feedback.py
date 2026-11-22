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


async def sensitivity(s: AsyncSession, home_id: uuid.UUID, kind: str) -> float:
    """How far past its usual band an alert of this kind must go for the home: 1 = the P95 band;
    each "not an anomaly" in the last 90 days adds half a band, at most three bands."""
    n = await s.scalar(
        select(func.count()).where(
            AlertFeedback.home_id == home_id,
            AlertFeedback.kind == kind,
            AlertFeedback.verdict == "not_anomaly",
            AlertFeedback.at >= datetime.now(UTC) - WINDOW,
        )
    )
    return min(MAX_FACTOR, 1.0 + STEP * (n or 0))
