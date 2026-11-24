import uuid
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import DemoScenario

# The simulated thermostat heater of a demo home (scenario "heater"): the replay adds it to the main
# meter, NILM hands it back to its own device, the device's advice re-prices its setpoint.
HEATER = {"setpoint_c": 16.0, "w_per_c": 180.0, "max_w": 2000.0, "hours": [[6, 9], [17, 23]]}


def heater_w(temp_c: float | None, local_hour: int, params: dict) -> float:
    p = {**HEATER, **params}
    if temp_c is None or temp_c != temp_c:  # no weather for the hour: no heating figure to make up
        return 0.0
    if not any(a <= local_hour < b for a, b in p["hours"]):
        return 0.0
    return min(p["max_w"], p["w_per_c"] * max(0.0, p["setpoint_c"] - temp_c))


async def scenarios_between(
    s: AsyncSession, home_id: uuid.UUID, lo: datetime, hi: datetime
) -> list[DemoScenario]:
    """Scenarios of the home whose window overlaps [lo, hi] (an open end runs on)."""
    rows = await s.scalars(
        select(DemoScenario)
        .where(
            DemoScenario.home_id == home_id,
            DemoScenario.starts_at <= hi,
            or_(DemoScenario.ends_at.is_(None), DemoScenario.ends_at > lo),
        )
        .order_by(DemoScenario.starts_at)
    )
    return list(rows)
