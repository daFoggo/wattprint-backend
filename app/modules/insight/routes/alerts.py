import uuid
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query

from app.common.exceptions import NotFoundError
from app.dependencies import DbSession
from app.modules.home.api import Membership, WritableMembership

from .. import services
from ..schemas import AlertDevice, AlertFeedbackIn, AlertRead, AlertUpdate

router = APIRouter()


@router.get("/alerts", summary="The home's alerts, unresolved first, then newest first")
async def alerts(
    member: Membership,
    db: DbSession,
    status: Literal["open", "acknowledged", "resolved"] | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[AlertRead]:
    rows = await services.list_alerts(db, member.home_id, status, limit)
    mine = await services.verdicts(db, member.user_id, [a.id for a, _ in rows])
    out = [
        AlertRead(
            id=a.id,
            kind=a.kind,
            severity=a.severity,
            status=a.status,
            ts=a.ts,
            resolved_at=a.resolved_at,
            device=AlertDevice(id=d.id, name=d.name, type=d.device_type_code) if d else None,
            payload=a.payload,
            feedback=mine.get(a.id),
        )
        for a, d in rows
    ]
    return [_by_day(a) for a in out] if member.detail == "daily" else out


def _by_day(alert: AlertRead) -> AlertRead:
    """The day only, as `copilot_ro.alert` shows a daily token: no clock time, and no start hour
    in an odd-hour alert (its `value`)."""
    hidden = {"start", "at"} | ({"value"} if alert.payload.get("signal") == "odd_hour" else set())
    day = alert.ts.astimezone(ZoneInfo("Asia/Ho_Chi_Minh"))
    return alert.model_copy(
        update={
            "ts": day.replace(hour=0, minute=0, second=0, microsecond=0),
            "resolved_at": None,
            "payload": {k: v for k, v in alert.payload.items() if k not in hidden},
        }
    )


@router.patch(
    "/alerts/{alert_id}",
    status_code=204,
    summary="Mark an alert seen (any member of the home)",
)
async def update_alert(
    alert_id: uuid.UUID, body: AlertUpdate, member: WritableMembership, db: DbSession
) -> None:
    if not await services.acknowledge(db, member.home_id, alert_id):
        raise NotFoundError("No such alert in this home", code="alert_not_found")


@router.post(
    "/alerts/{alert_id}/feedback",
    status_code=204,
    summary="A member says whether an alert was useful; 'not_anomaly' makes that kind less eager",
)
async def feedback(
    alert_id: uuid.UUID, body: AlertFeedbackIn, member: WritableMembership, db: DbSession
) -> None:
    if not await services.record_feedback(
        db, member.home_id, member.user_id, alert_id, body.verdict
    ):
        raise NotFoundError("No such alert in this home", code="alert_not_found")
    await db.commit()
