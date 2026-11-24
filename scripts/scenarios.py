"""Simulated loads the REFIT replay adds to a demo home's main meter (tb_demo_scenario).

heater: a thermostat heater on cold mornings and evenings, part of the home (the model learns it);
forgotten_load / base_up / away / echo_run: demo events, kept out of training. cold_spell changes
the weather only (energy.weather_inputs), and the heater reacts to it.
"""

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

from app.modules.ops.api import DemoScenario, ReadingRow, heater_w

HOME_TZ = ZoneInfo("Asia/Ho_Chi_Minh")


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
            elif sc.name == "echo_run":  # a real run of the device again, from the start
                shape = p.get("shape") or []
                k = int((r.ts - sc.starts_at).total_seconds() // 60)
                if shape and k < len(shape) * int(p.get("times", 1)):
                    watts += float(shape[k % len(shape)])
        out.append(replace(r, value=watts))
    return out
