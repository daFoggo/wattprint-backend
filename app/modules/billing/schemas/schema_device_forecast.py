import uuid
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict


class _Model(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class DeviceDay(_Model):
    date: date
    kwh: float | None
    kwh_p10: float | None
    kwh_p90: float | None
    amount: float | None


class DeviceAdvice(_Model):
    key: Literal[
        "fewer_runs", "heater_setpoint", "heater_earlier_off", "kettle_fill", "fridge_check"
    ]
    saved_kwh: float
    saved_amount: float  # the cycle's bill with it against without it (VAT included)
    avoids_tier: int | None  # the tier the cycle would no longer end in
    params: dict[str, float]


class DeviceFactor(_Model):
    key: Literal[
        "temperature", "humidity", "sun", "rain", "calendar", "occupancy", "trend", "other"
    ]
    kwh_day: float  # what it adds to a day ahead against the device's usual
    amount: float  # that over the 7 days ahead (VND)
    now: float | None  # evidence: the input's mean ahead (°C, %, W/m², mm a day, days off a week,
    before: float | None  # share of hours someone is home, kWh a day) and over the last 28 days
    recent_temp: float | None  # trend only: last week's °C when 1 °C+ unlike the 28 days'...
    usual_temp: float | None  # ...and the 28 days' (why the recent level moved)


class DeviceExplain(_Model):
    """The 7 whole days ahead against the device's usual (its daily mean over the last 28 days);
    the factors add up to the change; none for the weekday mean."""

    usual_kwh_day: float
    forecast_kwh_day: float
    explainable: bool  # false: the model misses the device's own past, so no factors are given
    factors: list[DeviceFactor]
    busiest: DeviceDay | None


class DeviceForecast(_Model):
    """One device's outlook: `method` "model" (its own model beat the weekday-hour mean in its
    holdout) or "weekday" (that mean); `confidence` from the shown method's holdout error;
    `explain` the week ahead against the device's usual."""

    device_id: uuid.UUID
    name: str
    type: str
    simulated: bool  # the demo home's simulated heater
    method: Literal["model", "weekday"]
    confidence: Literal["high", "medium", "low"]
    error_pct: float | None
    backtest_days: int
    next_days: list[DeviceDay]
    kwh: float
    kwh_p10: float | None
    kwh_p90: float | None
    amount: float
    explain: DeviceExplain | None
    advice: list[DeviceAdvice]


class DeviceForecasts(_Model):
    period_end: date
    as_of: date
    devices: list[DeviceForecast]  # by amount, highest first
