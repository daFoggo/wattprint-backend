"""Simulated loads the REFIT replay adds to a demo home's main meter (tb_demo_scenario).

heater: a thermostat heater on cold mornings and evenings, part of the home (the model learns it);
forgotten_load / base_up / away: demo events, kept out of training. cold_spell changes the weather
only (energy.weather_inputs), and the heater reacts to it.
"""

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

from app.modules.ops.api import DemoScenario, ReadingRow

HOME_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
HEATER = {"setpoint_c": 16.0, "w_per_c": 180.0, "max_w": 2000.0, "hours": [[6, 9], [17, 23]]}


def heater_w(temp_c: float, local_hour: int, params: dict) -> float:
    p = {**HEATER, **params}
    if temp_c is None or temp_c != temp_c:  # no weather for the hour: no heating figure to make up
        return 0.0
    if not any(a <= local_hour < b for a, b in p["hours"]):
        return 0.0
    return min(p["max_w"], p["w_per_c"] * max(0.0, p["setpoint_c"] - temp_c))


def _inside(sc: DemoScenario, ts: datetime) -> bool:
    return sc.starts_at <= ts and (sc.ends_at is None or ts < sc.ends_at)


def apply(
    rows: list[ReadingRow],
    scenarios: list[DemoScenario],
    temp_at: Callable[[datetime], float],
) -> list[ReadingRow]:
    """The rows as the meter would read them with the scenarios running; quality is kept."""
    if not scenarios:
        return rows
    out = []
    for r in rows:
        watts = r.value
        for sc in scenarios:
            if not _inside(sc, r.ts):
                continue
            p = sc.params or {}
            if sc.name == "heater":
                watts += heater_w(temp_at(r.ts), r.ts.astimezone(HOME_TZ).hour, p)
            elif sc.name == "forgotten_load":
                watts += float(p.get("watts", 800))
            elif sc.name == "base_up":
                watts += float(p.get("watts", 60))
            elif sc.name == "away":
                watts = min(watts, float(p.get("base_w", 120)))
        out.append(replace(r, value=watts))
    return out
