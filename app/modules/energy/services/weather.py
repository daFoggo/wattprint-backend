import asyncio
import logging
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import httpx

from app.config import settings

from ..utils import WeatherUnavailableError

log = logging.getLogger(__name__)

BASE = "https://api.openweathermap.org/data/2.5"
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
        async with httpx.AsyncClient(base_url=BASE, timeout=TIMEOUT_S) as client:
            current, forecast = await asyncio.gather(
                client.get("/weather", params=params), client.get("/forecast", params=params)
            )
            current.raise_for_status()
            forecast.raise_for_status()
    except httpx.HTTPError as e:
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
