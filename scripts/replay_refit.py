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
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
from sqlalchemy import text

from app.database import SessionLocal, engine
from app.modules.energy.api import weather_inputs
from app.modules.ops.api import ingest_readings, scenarios_between
from scripts import refit, scenarios

WINDOW = timedelta(hours=6)  # ~2.7k readings per ingest call
TAIL_S = 5
# Two replays race on every insert and the one without the newest scenario code can win.
LOCK = text("SELECT pg_try_advisory_lock(hashtextextended('replay_refit', 0))")


@dataclass
class Home:
    house: int
    shift_days: int
    df: pd.DataFrame
    last: datetime  # newest database time already stored for its main series
    key: str | None = None  # "5-heat": a second home on the same recording
    home_id: uuid.UUID | None = None


async def _with_scenarios(h: Home, rows: list, lo: datetime, hi: datetime) -> list:
    """The rows with the home's simulated loads (heater, demo events) added."""
    if h.home_id is None or not rows:
        return rows
    async with SessionLocal() as session:
        found = await scenarios_between(session, h.home_id, lo, hi)
        if not found:
            return rows
        temps = (await weather_inputs(session, h.home_id, lo, hi + timedelta(hours=1), hi))[
            "temp_c"
        ]
    return scenarios.apply(
        rows, found, lambda ts: temps.get(pd.Timestamp(ts).floor("h"), float("nan"))
    )


async def replay(h: Home, lo: datetime, hi: datetime, source: str = "replay") -> int:
    """Ingest the readings with database time in (lo, hi], in WINDOW steps. Returns new rows."""
    last_wall = h.df["wall"].iloc[-1].to_pydatetime()
    new = 0
    while lo < hi:
        step_hi = min(lo + WINDOW, hi)
        shift = refit.shift_for(step_hi, h.shift_days, last_wall)
        rows = await _with_scenarios(h, refit.rows_between(h.df, lo, step_hi, shift), lo, step_hi)
        if rows:
            async with SessionLocal() as session, session.begin():
                result = await ingest_readings(session, refit.meter(h.house, h.key), rows, source)
                new += result.rows_new
        lo = step_hi
    return new


async def homes(data_dir: Path) -> list[Home]:
    out, frames = [], {}
    async with SessionLocal() as session:
        marks = (
            await session.execute(
                text(
                    "SELECT source, shift_days FROM etl.tb_watermark WHERE segment = :seg "
                    "ORDER BY source"
                ),
                {"seg": refit.SEGMENT},
            )
        ).all()
        for w in marks:
            house, key = refit.house_of(w.source), refit.key_of(w.source)
            r = (
                await session.execute(
                    text(
                        "SELECT m.home_id, (SELECT r.ts FROM public.tb_reading r "
                        "  JOIN public.tb_series s USING (series_id) "
                        "  WHERE s.meter_id = m.id AND s.kind = 'main' "
                        "  ORDER BY r.ts DESC LIMIT 1) AS last "
                        "FROM public.tb_meter m WHERE m.serial = :m"
                    ),
                    {"m": refit.meter(house, key)},
                )
            ).first()
            if r is None or r.last is None:
                print(f"home {key}: no readings yet, run scripts.seed_demo_homes first", flush=True)
                continue
            if house not in frames:
                frames[house] = refit.load(data_dir / f"CLEAN_House{house}.csv")
            out.append(Home(house, w.shift_days, frames[house], r.last, key, r.home_id))
    return out


async def take_replay_lock(conn) -> bool:
    """True when no other replay holds the lock; it stays held while `conn` is open."""
    got = await conn.scalar(LOCK)
    await conn.commit()
    return bool(got)


async def main(once: bool) -> None:
    # shortcut: a database restart drops the lock while the replay keeps going;
    # re-check it per tail if replays get started by a supervisor.
    async with engine.connect() as lock:
        if not await take_replay_lock(lock):
            sys.exit("Another scripts.replay_refit is running: stop it first")
        await _run(once)


async def _run(once: bool) -> None:
    # Not __file__: piped in through `python -` the script has none.
    data_dir = Path(os.environ.get("REFIT_SEED_DIR") or "dataset")
    hs = await homes(data_dir)
    if not hs:
        sys.exit("No demo homes: run `python -m scripts.seed_demo_homes` first")
    now = datetime.now(UTC)
    for h in hs:
        print(
            f"home {h.key}: gap {h.last} -> {now}: {await replay(h, h.last, now)} new",
            flush=True,
        )
    while not once:
        await asyncio.sleep(TAIL_S)
        start, now = now, datetime.now(UTC)
        for h in hs:
            new = await replay(h, start, now)
            if new:
                print(f"{now:%H:%M:%S} home {h.key} +{new}", flush=True)


if __name__ == "__main__":
    asyncio.run(main("--once" in sys.argv))
