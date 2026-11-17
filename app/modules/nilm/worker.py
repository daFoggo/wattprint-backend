import asyncio
import logging
import time
from datetime import timedelta
from pathlib import Path

import torch

from app.config import settings
from app.database import SessionLocal, engine

from .services import engine as nilm_engine
from .services import run_home, targets

log = logging.getLogger("nilm.worker")

BACKOFF_MAX_S = 600


async def main() -> None:
    """Every nilm_poll_s: catch each home up to its newest reading.

    A home that fails is retried after 1, 2, 4 ... minutes (at most 10) without holding up the
    others; its readings are untouched and its checkpoint stays put until a pass succeeds.
    """
    torch.set_num_threads(settings.nilm_threads)
    model_dir = Path(settings.nilm_model_dir)
    history = timedelta(days=settings.nilm_history_days)
    failures: dict = {}  # home_id -> (consecutive failures, monotonic time of next try)
    while True:
        async with SessionLocal() as session:
            homes = await targets(session)
        for t in homes:
            count, next_try = failures.get(t.home_id, (0, 0.0))
            if time.monotonic() < next_try:
                continue
            started = time.monotonic()
            try:
                written = await run_home(engine, t, nilm_engine.load, model_dir, history)
            except Exception:
                count += 1
                delay = min(60 * 2 ** (count - 1), BACKOFF_MAX_S)
                failures[t.home_id] = (count, time.monotonic() + delay)
                log.exception("home %s failed (%d in a row), retry in %ds", t.home_id, count, delay)
                continue
            failures.pop(t.home_id, None)
            if written:
                log.info(
                    "home %s: %d estimates in %.1fs (%s)",
                    t.home_id,
                    written,
                    time.monotonic() - started,
                    t.model_version,
                )
        await asyncio.sleep(settings.nilm_poll_s)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(main())
