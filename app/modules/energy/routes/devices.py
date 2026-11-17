import uuid
from datetime import UTC, datetime

from fastapi import APIRouter

from app.dependencies import DbSession

from .. import services
from ..dependencies import CurrentHome
from ..schemas import Activity, Cycle, DayEnergy, Device, DeviceDetail, PowerStep
from ..utils import DeviceNotFoundError

router = APIRouter()


def _ms(ts: datetime) -> int:
    return int(ts.timestamp() * 1000)


def _device(row: services.DeviceRow) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "room": row.room,
        "type": row.type,
        "show_on_timeline": row.show_on_timeline,
        "on": row.on,
        "watts": row.watts,
        "today_kwh": row.today_kwh,
        "month_kwh": row.month_kwh,
        "week_kwh": row.week_kwh,
    }


def _cycle(c: services.Cycle) -> dict:
    return {"start": _ms(c.start), "end": _ms(c.end) if c.end else None, "kwh": c.kwh}


@router.get("/devices", summary="The home's devices found by NILM: power now, today, month, week")
async def list_devices(home_id: CurrentHome, db: DbSession) -> list[Device]:
    rows = await services.devices(db, home_id, datetime.now(UTC))
    return [Device(**_device(r)) for r in rows]


@router.get("/devices/{device_id}", summary="One device: this month by day, last 24 h, its runs")
async def get_device(device_id: uuid.UUID, home_id: CurrentHome, db: DbSession) -> DeviceDetail:
    d = await services.device_detail(db, home_id, device_id, datetime.now(UTC))
    if d is None:
        raise DeviceNotFoundError
    return DeviceDetail(
        **_device(d.device),
        typical_w=d.device.typical_w,
        tip=d.device.tip,
        avg_on_w=d.avg_on_w,
        peak_w=d.peak_w,
        home_share=d.home_share,
        days=[DayEnergy(date=day, kwh=kwh) for day, kwh in d.days],
        power=[PowerStep(ts=_ms(ts), watts=w) for ts, w in d.power],
        cycles=[Cycle(**_cycle(c)) for c in d.cycles],
    )


@router.get("/activity", summary="Runs started in the last 24 h by devices on the timeline")
async def activity(home_id: CurrentHome, db: DbSession) -> list[Activity]:
    return [
        Activity(**_cycle(c), device=row.id, name=row.name, room=row.room, type=row.type)
        for row, c in await services.activity(db, home_id, datetime.now(UTC))
    ]
