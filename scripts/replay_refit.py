"""Replay every demo REFIT home into the live pipeline, standing in for the real meters.

For each meter seeded by scripts/seed_demo_homes.py (etl.tb_watermark segment 'demo'): fill the gap
from its newest main reading to now, then tail every TAIL_S seconds. Every sample goes through
ops.ingest_readings, like a sensor batch would. Time mapping: scripts/refit.py. Past the end of
a recording it keeps replaying its last week; a recording gap shows as no data.

Runs inside the api container, where the app, the database and the CSVs (/data) are available:
    docker compose exec -T api python -m scripts.replay_refit            # gap + tail
    docker compose exec -T api python -m scripts.replay_refit --once     # gap only
"""

import asyncio
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
from sqlalchemy import text

from app.database import SessionLocal
from app.modules.ops.api import ingest_readings
from scripts import refit

WINDOW = timedelta(hours=6)  # ~2.7k readings per ingest call
TAIL_S = 5


@dataclass
class Home:
    house: int
    shift_days: int
    df: pd.DataFrame
    last: datetime  # newest database time already stored for its main series


async def replay(h: Home, lo: datetime, hi: datetime, source: str = "replay") -> int:
    """Ingest the readings with database time in (lo, hi], in WINDOW steps. Returns new rows."""
    last_wall = h.df["wall"].iloc[-1].to_pydatetime()
    new = 0
    while lo < hi:
        step_hi = min(lo + WINDOW, hi)
        shift = refit.shift_for(step_hi, h.shift_days, last_wall)
        rows = refit.rows_between(h.df, lo, step_hi, shift)
        if rows:
            async with SessionLocal() as session, session.begin():
                result = await ingest_readings(session, refit.meter(h.house), rows, source)
                new += result.rows_new
        lo = step_hi
    return new


async def homes(data_dir: Path) -> list[Home]:
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT w.source, w.shift_days, ("
                    "  SELECT r.ts FROM public.tb_reading r "
                    "  JOIN public.tb_series s USING (series_id) "
                    "  JOIN public.tb_meter m ON m.id = s.meter_id "
                    "  WHERE m.serial = 'REFIT-H' || substring(w.source FROM 'House([0-9]+)') "
                    "    AND s.kind = 'main' ORDER BY r.ts DESC LIMIT 1) AS last "
                    "FROM etl.tb_watermark w WHERE w.segment = :seg ORDER BY w.source"
                ),
                {"seg": refit.SEGMENT},
            )
        ).all()
    out = []
    for r in rows:
        house = refit.house_of(r.source)
        if r.last is None:
            print(f"house {house}: no readings yet, run scripts.seed_demo_homes first", flush=True)
            continue
        df = refit.load(data_dir / f"CLEAN_House{house}.csv")
        out.append(Home(house, r.shift_days, df, r.last))
    return out


async def main(once: bool) -> None:
    # Not __file__: piped in through `python -` the script has none.
    data_dir = Path(os.environ.get("REFIT_SEED_DIR") or "dataset")
    hs = await homes(data_dir)
    if not hs:
        sys.exit("No demo homes: run `python -m scripts.seed_demo_homes` first")
    now = datetime.now(UTC)
    for h in hs:
        print(
            f"house {h.house}: gap {h.last} -> {now}: {await replay(h, h.last, now)} new",
            flush=True,
        )
    while not once:
        await asyncio.sleep(TAIL_S)
        start, now = now, datetime.now(UTC)
        for h in hs:
            new = await replay(h, start, now)
            if new:
                print(f"{now:%H:%M:%S} house {h.house} +{new}", flush=True)


if __name__ == "__main__":
    asyncio.run(main("--once" in sys.argv))
