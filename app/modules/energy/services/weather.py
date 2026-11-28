import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common import outbound
from app.config import settings
from app.modules.ops.api import scenarios_between

from ..models import HomeWeatherHourly as W
from ..utils import WeatherUnavailableError

log = logging.getLogger(__name__)

TTL_S = 600  # OpenWeather refreshes about every 10 minutes
TIMEOUT_S = 5.0
SLOTS = 8  # 3-hour forecast steps: the next 24 hours


@dataclass(frozen=True)
class Sky:
    description: str
    icon: str  # OpenWeather icon code: "01d" clear by day, "10n" rain at night


@dataclass(frozen=True)
class Now:
    dt: int
    temp: float
    feels_like: float
    humidity: int
    wind_speed: float
    sky: Sky


@dataclass(frozen=True)
class Slot:
    dt: int
    temp: float
    pop: float  # probability of precipitation, 0..1
    sky: Sky


@dataclass(frozen=True)
class Weather:
    now: Now
    next: list[Slot]


_cache: dict[tuple, tuple[float, Weather]] = {}
_locks: dict[tuple, asyncio.Lock] = {}


def _sky(item: dict[str, Any]) -> Sky:
    w = item["weather"][0]
    return Sky(description=str(w["description"]), icon=str(w["icon"]))


def parse(current: dict[str, Any], forecast: dict[str, Any]) -> Weather:
    try:
        now = Now(
            dt=int(current["dt"]),
            temp=float(current["main"]["temp"]),
            feels_like=float(current["main"]["feels_like"]),
            humidity=int(current["main"]["humidity"]),
            wind_speed=float(current["wind"]["speed"]),
            sky=_sky(current),
        )
        slots = [
            Slot(dt=int(s["dt"]), temp=float(s["main"]["temp"]), pop=float(s["pop"]), sky=_sky(s))
            for s in forecast["list"][:SLOTS]
        ]
    except (KeyError, IndexError, TypeError, ValueError) as e:
        log.warning("unexpected OpenWeather answer: %r", e)
        raise WeatherUnavailableError from e
    if not slots:
        log.warning("OpenWeather returned no forecast")
        raise WeatherUnavailableError
    return Weather(now=now, next=slots)


async def _fetch(lat: Decimal, lon: Decimal, lang: str) -> Weather:
    params = {
        "lat": str(lat),
        "lon": str(lon),
        "units": "metric",
        "lang": lang,  # OpenWeather writes the sky's description ("mây rải rác") in it
        "appid": settings.openweather_api_key,
    }
    try:
        # no home, no person in the row
        await outbound.record("openweather", "weather", ["province location"])
        async with outbound.client("openweather", timeout=TIMEOUT_S) as client:
            current, forecast = await asyncio.gather(
                client.get("/weather", params=params), client.get("/forecast", params=params)
            )
            current.raise_for_status()
            forecast.raise_for_status()
    except (httpx.HTTPError, SQLAlchemyError) as e:
        log.warning("OpenWeather failed: %r", e)
        raise WeatherUnavailableError from e
    return parse(current.json(), forecast.json())


async def weather_at(lat: Decimal, lon: Decimal, lang: str) -> Weather:
    """The weather at a place, cached per (place, language); one fetch at a time per key."""
    if not settings.openweather_api_key:
        raise WeatherUnavailableError
    key = (str(lat), str(lon), lang)
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < TTL_S:
        return hit[1]
    async with _locks.setdefault(key, asyncio.Lock()):
        hit = _cache.get(key)
        if hit and time.monotonic() - hit[0] < TTL_S:
            return hit[1]
        weather = await _fetch(lat, lon, lang)
        _cache[key] = (time.monotonic(), weather)
        return weather


SKY_WORDS = {
    "vi": {"01": "trời quang", "02": "ít mây", "03": "mây rải rác", "04": "nhiều mây", "10": "mưa"},
    "en": {
        "01": "clear sky",
        "02": "few clouds",
        "03": "scattered clouds",
        "04": "overcast",
        "10": "rain",
    },
}
SITE = {
    "vi": "Nơi đo dữ liệu nhà demo (Loughborough, Anh)",
    "en": "Where the demo home was recorded (Loughborough, UK)",
}


def _stored_sky(cloud: float | None, precip: float | None, is_day: bool | None, lang: str) -> Sky:
    """An OpenWeather-style icon and words from the stored hour, so the card draws it the same."""
    if (precip or 0) >= 0.2:
        code = "10"
    else:
        cloud = cloud or 0
        code = "04" if cloud >= 70 else "03" if cloud >= 30 else "02" if cloud >= 10 else "01"
    return Sky(description=SKY_WORDS[lang][code], icon=code + ("d" if is_day else "n"))


async def stored_weather(
    s: AsyncSession, home_id: uuid.UUID, now: datetime, lang: str
) -> tuple[str, Weather] | None:
    """The home's stored weather (a demo home's recording site) for the hour of `now` and the next
    24 hours in 3-hour steps, with the place's label; None when nothing is stored for now."""
    hour = now.replace(minute=0, second=0, microsecond=0)
    rows = {
        r.ts: r
        for r in await s.scalars(
            select(W).where(W.home_id == home_id, W.ts >= hour, W.ts <= hour + timedelta(hours=24))
        )
    }
    cold: dict[datetime, float] = {}  # the card shows the weather the model is given
    for sc in await scenarios_between(s, home_id, hour, hour + timedelta(hours=24)):
        if sc.name == "cold_spell":
            for ts in rows:
                if sc.starts_at <= ts and (sc.ends_at is None or ts < sc.ends_at):
                    cold[ts] = cold.get(ts, 0.0) + float(sc.params.get("delta_c", 0))
    cur = rows.get(hour)
    if cur is None or cur.temp_c is None:
        return None
    slots = [
        Slot(
            dt=int(r.ts.timestamp()),
            temp=float(r.temp_c) - cold.get(r.ts, 0.0),
            pop=1.0 if (r.precip_mm or 0) >= 0.2 else 0.0,
            sky=_stored_sky(r.cloud_pct, r.precip_mm, r.is_day, lang),
        )
        for k in range(1, SLOTS + 1)
        if (r := rows.get(hour + timedelta(hours=3 * k))) is not None and r.temp_c is not None
    ]
    now_ = Now(
        dt=int(hour.timestamp()),
        temp=float(cur.temp_c) - cold.get(hour, 0.0),
        feels_like=float(cur.apparent_c if cur.apparent_c is not None else cur.temp_c)
        - cold.get(hour, 0.0),
        humidity=int(round(cur.humidity_pct or 0)),
        wind_speed=float(cur.wind_ms or 0),
        sky=_stored_sky(cur.cloud_pct, cur.precip_mm, cur.is_day, lang),
    )
    return SITE[lang], Weather(now=now_, next=slots)
