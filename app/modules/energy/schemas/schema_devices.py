import uuid
from datetime import date

from pydantic import BaseModel

# Shapes of wattprint-web features/energy/schemas.ts (DeviceSchema, DeviceDetailSchema,
# ActivitySchema). Instants inside charts and runs are epoch milliseconds, as the web reads them.


class DeviceEstimate(BaseModel):
    """How far NILM's share for this device can be trusted, as a level only: the scores behind it
    (held-out test against the appliance's plug) stay internal, a real home has no plugs."""

    level: str  # high, medium, low


class Device(BaseModel):
    id: uuid.UUID
    name: str
    room: str | None
    type: str  # cat_device_type.code
    show_on_timeline: bool
    on: bool
    watts: float
    today_kwh: float
    month_kwh: float  # from the 1st of this month, local time
    week_kwh: list[float]  # the last 7 local days, today last
    estimate: DeviceEstimate | None = None  # None: the home's model was never scored for this type


class Cycle(BaseModel):
    start: int
    end: int | None  # None while still running
    kwh: float


class DayEnergy(BaseModel):
    date: date
    kwh: float


class DeviceDay(DayEnergy):
    peak_w: float
    longest_min: int  # the longest run that started that day


class PowerStep(BaseModel):
    ts: int
    watts: float


class DeviceDetail(Device):
    typical_w: int | None
    tip: str | None
    avg_on_w: float  # this month, over the minutes it was on
    peak_w: float  # this month
    home_share: float  # of the main meter's kWh this month, 0..1
    days: list[DeviceDay]  # this month and at least the last 30 days, today last
    power: list[PowerStep]  # last 24 h in 5-minute steps
    cycles: list[Cycle]  # runs in the last 24 h, oldest first


class Activity(Cycle):
    device: uuid.UUID
    name: str
    room: str | None
    type: str  # cat_device_type.code
