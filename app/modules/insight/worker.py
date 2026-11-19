import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import text

from app.config import settings
from app.database import engine

from .services import jobs

log = logging.getLogger("insight.worker")

LOCK = text("SELECT pg_try_advisory_lock(hashtextextended(:k, 0))")
UNLOCK = text("SELECT pg_advisory_unlock(hashtextextended(:k, 0))")


@dataclass
class Job:
    name: str
    every_s: int
    run: Callable[[datetime], Awaitable[None]]
    next_at: float = 0.0  # monotonic; 0 = due at start


JOBS = [
    Job("bills", 3600, jobs.bills),
    Job("forecasts", 86_400, jobs.forecasts),
    Job("cohorts", 86_400, jobs.cohorts),
    Job("alerts", 300, jobs.alerts),
    Job("mail", 300, jobs.mail),
    Job("upkeep", 3600, jobs.upkeep),
]


async def run_due(job: Job) -> None:
    """Run the job unless another worker holds it; a failure is logged and retried next time."""
    async with engine.connect() as lock:
        got = await lock.scalar(LOCK, {"k": f"insight:{job.name}"})
        await lock.commit()
        if not got:
            return
        try:
            started = time.monotonic()
            await job.run(datetime.now(UTC))
            log.info("%s done in %.1fs", job.name, time.monotonic() - started)
        except Exception:
            log.exception("%s failed", job.name)
        finally:
            await lock.execute(UNLOCK, {"k": f"insight:{job.name}"})
            await lock.commit()


async def main() -> None:
    while True:
        for job in JOBS:
            if time.monotonic() >= job.next_at:
                job.next_at = time.monotonic() + job.every_s
                await run_due(job)
        await asyncio.sleep(settings.insight_poll_s)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(main())
