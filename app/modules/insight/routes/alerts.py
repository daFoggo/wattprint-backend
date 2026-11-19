import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Query

from app.common.exceptions import NotFoundError
from app.dependencies import DbSession
from app.modules.energy.api import CurrentHome

from .. import services
from ..schemas import AlertDevice, AlertRead, AlertUpdate

router = APIRouter()


@router.get("/alerts", summary="The home's alerts, unresolved first, then newest first")
async def alerts(
    home_id: CurrentHome,
    db: DbSession,
    status: Literal["open", "acknowledged", "resolved"] | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[AlertRead]:
    return [
        AlertRead(
            id=a.id,
            kind=a.kind,
            severity=a.severity,
            status=a.status,
            ts=a.ts,
            resolved_at=a.resolved_at,
            device=AlertDevice(id=d.id, name=d.name, type=d.device_type_code) if d else None,
            payload=a.payload,
        )
        for a, d in await services.list_alerts(db, home_id, status, limit)
    ]


@router.patch(
    "/alerts/{alert_id}",
    status_code=204,
    summary="Mark an alert seen (any member of the home)",
)
async def update_alert(
    alert_id: uuid.UUID, body: AlertUpdate, home_id: CurrentHome, db: DbSession
) -> None:
    if not await services.acknowledge(db, home_id, alert_id):
        raise NotFoundError("No such alert in this home", code="alert_not_found")
