import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np

from app.config import settings

BLOCK_H = 4  # peers start in the same 4-hour block of the day
TEMP_C = 3.0  # and within ±3 °C
MIN_PEERS = 8
LONGER = 1.5
RARE = 0.03  # a start hour seen on under 3 % of days is rare
MIN_DAYS, MIN_RUNS = 28, 20
DENSER = 1.2  # cycling 20 % more than at the same temperature weeks ago
DENSER_DAYS = 3


@dataclass(frozen=True)
class Run:
    minutes: float
    kwh: float
    start_hour: int  # local
    temp_c: float | None  # outdoor, at its start
    day: int  # local day number, for "how many days"


def _vnd(kwh: float, price: float) -> float:
    return float(round(kwh * price))


def daily_excess(actual: float, p50: float, p95: float, price: float, factor: float) -> dict | None:
    """D1: today's kWh past the device model's band for today's context, worth the money."""
    excess = actual - p50
    if actual <= p50 + factor * (p95 - p50) or _vnd(excess, price) < settings.device_min_vnd:
        return None
    return {
        "signal": "daily",
        "value": round(actual, 2),
        "usual": round(p50, 2),
        "unit": "kWh",
        "excess_kwh": round(excess, 2),
        "excess_vnd": _vnd(excess, price),
    }


def outside_events(
    rows: Sequence[Any], events: list[tuple[datetime, datetime | None]]
) -> list[Any]:
    """Runs (anything with start_ts and end_ts) that overlap no demo event; an event with no end
    runs on. A staged run must not become history: repeated takes would raise the device's own
    threshold."""
    return [
        r
        for r in rows
        if not any(r.end_ts > a and (b is None or r.start_ts < b) for a, b in events)
    ]


def peers_of(run: Run, history: list[Run]) -> list[Run]:
    """Runs of the same device that started in the same block of the day at a similar
    temperature (all of them when the temperature is unknown)."""
    block = run.start_hour // BLOCK_H
    return [
        r
        for r in history
        if r.start_hour // BLOCK_H == block
        and (run.temp_c is None or r.temp_c is None or abs(r.temp_c - run.temp_c) <= TEMP_C)
    ]


def long_run(run: Run, peers: list[Run], price: float, factor: float) -> dict | None:
    """D2: a run longer and dearer than its peers' 95th percentile and 1.5× their median."""
    if len(peers) < MIN_PEERS:
        return None
    mins, kwhs = [p.minutes for p in peers], [p.kwh for p in peers]
    m_med, k_med = statistics.median(mins), statistics.median(kwhs)
    over = LONGER * factor
    if not (
        run.minutes > np.percentile(mins, 95)
        and run.minutes >= over * m_med
        and run.kwh > np.percentile(kwhs, 95)
        and run.kwh >= over * k_med
    ):
        return None
    if _vnd(run.kwh - k_med, price) < settings.device_min_vnd:
        return None
    return {
        "signal": "long_run",
        "value": round(run.minutes),
        "usual": round(m_med),
        "unit": "min",
        "excess_kwh": round(run.kwh - k_med, 2),
        "excess_vnd": _vnd(run.kwh - k_med, price),
    }


def odd_hour(
    start_hour: int, days_at_hour: int, days: int, runs: int, factor: float = 1.0
) -> dict | None:
    """D3: a start at an hour the device ran at on under 3 % of its days (enough history)."""
    if days < MIN_DAYS or runs < MIN_RUNS or days_at_hour / days >= RARE / factor:
        return None
    return {
        "signal": "odd_hour",
        "value": start_hour,
        "usual": round(100 * days_at_hour / days, 1),
        "unit": "%",
    }


def denser_cycling(
    recent: list[float], past: float, daily_kwh: float, price: float, factor: float = 1.0
) -> dict | None:
    """D4: a cycling device (fridge) on a larger share of the time on each of the last 3 days
    than at the same temperature 4–8 weeks ago; the extra energy is a day's cost."""
    if len(recent) < DENSER_DAYS or past <= 0:
        return None
    bar = 1 + (DENSER - 1) * factor
    if any(r < bar * past for r in recent[-DENSER_DAYS:]):
        return None
    now = float(np.mean(recent[-DENSER_DAYS:]))
    extra = (now / past - 1) * daily_kwh
    if _vnd(extra, price) < settings.device_min_vnd:
        return None
    return {
        "signal": "denser",
        "value": round(now, 2),
        "usual": round(past, 2),
        "unit": "share",
        "excess_kwh": round(extra, 2),
        "excess_vnd": _vnd(extra, price),
    }
