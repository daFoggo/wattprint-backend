"""Device estimates for a demo home's older readings, before its first estimate, without touching
the NILM worker's checkpoint or any estimate already stored.

    docker compose exec -T nilm python -m scripts.backfill_nilm --house 2 --days 365
"""

import argparse
import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import settings
from app.database import engine

CHUNK = timedelta(days=1)


def backfill_windows(
    lo: datetime, first: datetime, chunk: timedelta
) -> list[tuple[datetime, datetime]]:
    """[lo, first) in chunk steps; the last one ends at `first`."""
    out, a = [], lo
    while a < first:
        b = min(a + chunk, first)
        out.append((a, b))
        a = b
    return out


async def main(key: str, days: int) -> None:
    import torch

    from app.modules.energy.api import backfill_aggregates
    from app.modules.nilm.services import engine as nilm_engine
    from app.modules.nilm.services import runner, windows
    from app.modules.nilm.services.devices import ensure_devices
    from app.modules.ops.api import ingest_estimates
    from scripts import refit

    torch.set_num_threads(settings.nilm_threads)  # leave the worker and the API their share
    house = int(key.split("-")[0])
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as s:
        home_id = await s.scalar(
            text("SELECT home_id FROM public.tb_meter WHERE serial = :m"),
            {"m": refit.meter(house, key)},
        )
        t = next((t for t in await runner.targets(s) if t.home_id == home_id), None)
        if t is None:
            raise SystemExit(f"home {key}: no main series or NILM model")
        first = await s.scalar(
            text(
                "SELECT min(e.ts) FROM public.tb_device_estimate e "
                "JOIN public.tb_series x USING (series_id) WHERE x.home_id = :h"
            ),
            {"h": home_id},
        )
    first = first or datetime.now(UTC)
    lo = datetime.now(UTC) - timedelta(days=days)
    bundle = nilm_engine.load(Path(settings.nilm_model_dir) / t.artifact)
    pad = 2 * bundle.window * windows.STEP.to_pytimedelta()
    total = 0
    for a, b in backfill_windows(lo, first, CHUNK):
        async with sessions() as s, s.begin():
            open_head = await runner._open_head(s, t.main_series, a - pad)
            ts, watts = await runner._read(s, t.main_series, a - pad, b + pad)
            if len(ts) == 0:
                continue
            series = await ensure_devices(s, t.home_id, bundle.labels)
            p = windows.plan(ts, watts, a, bundle.window, bundle.window // 2, open_head)
            rows = runner.compute(bundle, p, t.timezone, series) if p else []
            rows = [r for r in rows if a <= r[0] < b]
            run_id = await s.scalar(
                text(
                    "INSERT INTO public.tb_inference_run (home_id, model_name, model_version, "
                    "window_start, window_end, status, finished_at) "
                    "VALUES (:h, :n, :v, :a, :b, 'ok', now()) RETURNING run_id"
                ),
                {"h": t.home_id, "n": t.model_name, "v": t.model_version, "a": a, "b": b},
            )
            total += await ingest_estimates(s, run_id, rows)
        print(f"home {key}: {a:%Y-%m-%d} +{len(rows)}", flush=True)
    async with engine.connect() as c:
        c = await c.execution_options(isolation_level="AUTOCOMMIT")
        await backfill_aggregates(c, lo, first)
    print(f"home {key}: {total} estimates before {first}", flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--house", required=True)
    p.add_argument("--days", type=int, default=365)
    a = p.parse_args()
    asyncio.run(main(a.house, a.days))
