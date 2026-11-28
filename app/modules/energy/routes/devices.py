import uuid
from datetime import UTC, datetime

from fastapi import APIRouter

from app.dependencies import DbSession
from app.modules.home.api import Membership

from .. import services
from ..dependencies import DetailedHome
from ..schemas import Activity, Cycle, Device, DeviceDay, DeviceDetail, PowerStep
from ..utils import DeviceNotFoundError

router = APIRouter()


def _ms(ts: datetime) -> int:
    return int(ts.timestamp() * 1000)


def _device(row: services.DeviceRow, daily: bool = False) -> dict:
    """`daily`: without what the device does now (R4.3)."""
    return {
        "id": row.id,
        "name": row.name,
        "room": row.room,
        "type": row.type,
        "show_on_timeline": row.show_on_timeline,
        "on": None if daily else row.on,
        "watts": None if daily else row.watts,
        "today_kwh": row.today_kwh,
        "month_kwh": row.month_kwh,
        "week_kwh": row.week_kwh,
        "estimate": {"level": row.estimate.level} if row.estimate else None,
    }


def _cycle(c: services.Cycle) -> dict:
    return {"start": _ms(c.start), "end": _ms(c.end) if c.end else None, "kwh": c.kwh}


@router.get("/devices", summary="The home's devices found by NILM: power now, today, month, week")
async def list_devices(member: Membership, db: DbSession) -> list[Device]:
    rows = await services.devices(db, member.home_id, datetime.now(UTC))
    return [Device(**_device(r, member.detail == "daily")) for r in rows]


@router.get("/devices/{device_id}", summary="One device: this month by day, last 24 h, its runs")
async def get_device(device_id: uuid.UUID, member: Membership, db: DbSession) -> DeviceDetail:
    daily = member.detail == "daily"
    d = await services.device_detail(db, member.home_id, device_id, datetime.now(UTC))
    if d is None:
        raise DeviceNotFoundError
    return DeviceDetail(
        **_device(d.device, daily),
        typical_w=d.device.typical_w,
        tip=d.device.tip,
        avg_on_w=d.avg_on_w,
        peak_w=d.peak_w,
        home_share=d.home_share,
        days=[
            DeviceDay(date=day, kwh=kwh, peak_w=peak, longest_min=run)
            for day, kwh, peak, run in d.days
        ],
        power=[] if daily else [PowerStep(ts=_ms(ts), watts=w) for ts, w in d.power],
        cycles=[] if daily else [Cycle(**_cycle(c)) for c in d.cycles],
    )


@router.get("/activity", summary="Runs started in the last 24 h by devices on the timeline")
async def activity(home_id: DetailedHome, db: DbSession) -> list[Activity]:
    return [
        Activity(**_cycle(c), device=row.id, name=row.name, room=row.room, type=row.type)
        for row, c in await services.activity(db, home_id, datetime.now(UTC))
    ]
