"""Device estimates for the days of a demo home's history that have none (before its first
estimate and in the holes a stopped run left), up to the NILM worker's checkpoint; never touches
the checkpoint or a day that already has estimates. Re-runnable: done days are skipped.

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


def missing_windows(
    lo: datetime, hi: datetime, have: set[datetime], chunk: timedelta
) -> list[tuple[datetime, datetime]]:
    """The chunks of [lo, hi) whose start is not in `have` (chunks that already have estimates)."""
    return [w for w in backfill_windows(lo, hi, chunk) if w[0] not in have]


REFRESH_EVERY = 15  # chunks between aggregate refreshes, so a stopped run keeps what it did


async def main(key: str, days: int, redo: bool = False) -> None:
    import torch

    from app.modules.energy.api import backfill_aggregates
    from app.modules.nilm.services import engine as nilm_engine
    from app.modules.nilm.services import runner, windows
    from app.modules.nilm.services.devices import HEATER, ensure_devices
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
        hi = await s.scalar(
            text(
                "SELECT last_ts FROM public.tb_ingest_checkpoint "
                "WHERE source = 'nilm' AND series_id = :s"
            ),
            {"s": t.main_series},
        )
        hi = hi or datetime.now(UTC)
        lo = (datetime.now(UTC) - timedelta(days=days)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        have = {
            lo + timedelta(days=int(k))
            for k in await s.scalars(
                text(
                    "SELECT DISTINCT floor(extract(epoch FROM e.ts - :lo) / 86400) "
                    "FROM public.tb_device_estimate e JOIN public.tb_series x USING (series_id) "
                    "WHERE x.home_id = :h AND e.ts >= :lo AND e.ts < :hi"
                ),
                {"h": home_id, "lo": lo, "hi": hi},
            )
        }
    bundle = nilm_engine.load(Path(settings.nilm_model_dir) / t.artifact)
    pad = 2 * bundle.window * windows.STEP.to_pytimedelta()
    # --redo: every day again (estimates are upserted), e.g. after the heater split changed Other.
    total, todo = 0, missing_windows(lo, hi, set() if redo else have, CHUNK)
    print(f"home {key}: {len(todo)} days to fill in [{lo:%Y-%m-%d}, {hi:%Y-%m-%d})", flush=True)

    async def refresh(a: datetime, b: datetime) -> None:
        async with engine.connect() as c:
            c = await c.execution_options(isolation_level="AUTOCOMMIT")
            await backfill_aggregates(c, a, b)

    since = None
    for i, (a, b) in enumerate(todo, 1):
        async with sessions() as s, s.begin():
            open_head = await runner._open_head(s, t.main_series, a - pad)
            ts, watts = await runner._read(s, t.main_series, a - pad, b + pad)
            if len(ts) == 0:
                continue
            heaters, temps = await runner.heater_inputs(s, t.home_id, a - pad, b + pad)
            series = await ensure_devices(s, t.home_id, bundle.labels, (HEATER,) if heaters else ())
            p = windows.plan(ts, watts, a, bundle.window, bundle.window // 2, open_head)
            heater = (
                runner.heater_watts(p.series.index, heaters, temps, t.timezone)
                if p and heaters
                else None
            )
            rows = runner.compute(bundle, p, t.timezone, series, heater) if p else []
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
        since = since or a
        print(f"home {key}: {a:%Y-%m-%d} +{len(rows)} ({i}/{len(todo)})", flush=True)
        if i % REFRESH_EVERY == 0:
            await refresh(since, b)
            since = None
    if since is not None:
        await refresh(since, todo[-1][1])
    print(f"home {key}: {total} estimates in {len(todo)} days", flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--house", required=True)
    p.add_argument("--days", type=int, default=365)
    p.add_argument("--redo", action="store_true", help="recompute days that have estimates too")
    a = p.parse_args()
    asyncio.run(main(a.house, a.days, a.redo))
