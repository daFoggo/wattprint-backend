"""Replay REFIT House 2 into the live pipeline, standing in for the real meter.

Fills the gap from the newest stored main-meter reading to now, then tails every TAIL_S seconds.
Every sample goes through ops.ingest_readings, like a sensor batch would. The CSV is shifted by
the seed's shift plus whole weeks (weekday kept) so each window lands inside the recording.

Runs inside the api container, where the app, the database and the CSV (/data) are available.
Past the end of the recording it keeps replaying the last week; a recording gap shows as no data:
    docker compose exec -T api python -m scripts.replay_refit            # gap + tail
    docker compose exec -T api python -m scripts.replay_refit --once     # gap only
"""

import asyncio
import math
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
from sqlalchemy import text

from app.database import SessionLocal
from app.modules.ops.api import ReadingRow, ingest_readings

SOURCE = "refit/CLEAN_House2.csv"  # the seed's etl.tb_watermark source, holds its shift_days
METER = "REFIT-H2"
CHANNELS = ("Aggregate", *(f"Appliance{i}" for i in range(1, 10)))
WEEK = timedelta(days=7)
WINDOW = timedelta(hours=6)  # ~3k CSV rows, ~30k readings per ingest call
TAIL_S = 5


def load_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(
        path, usecols=["Unix", *CHANNELS, "Issues"], dtype={c: "float32" for c in CHANNELS}
    )
    df["ts"] = pd.to_datetime(df["Unix"], unit="s", utc=True)
    return df.set_index("ts").sort_index()


def shift_for(db_hi: datetime, base: timedelta, last: datetime) -> timedelta:
    """The smallest base + k weeks (k >= 0) that maps db_hi to a moment inside the recording."""
    return base + max(0, math.ceil((db_hi - base - last) / WEEK)) * WEEK


def rows_in(df: pd.DataFrame, lo: datetime, hi: datetime, shift: timedelta) -> list[ReadingRow]:
    """Readings with database time in (lo, hi]; NaN cells are recording gaps, not bad rows."""
    part = df.loc[(df.index > lo - shift) & (df.index <= hi - shift)]
    rows = []
    for ts, rec in part.iterrows():
        when = (ts + shift).to_pydatetime()
        quality = int(rec["Issues"] == 1)
        rows += [
            ReadingRow(when, ch, float(rec[ch]), quality) for ch in CHANNELS if pd.notna(rec[ch])
        ]
    return rows


async def replay(df: pd.DataFrame, base: timedelta, lo: datetime, hi: datetime) -> int:
    last = df.index[-1].to_pydatetime()
    new = 0
    while lo < hi:
        step_hi = min(lo + WINDOW, hi)
        rows = rows_in(df, lo, step_hi, shift_for(step_hi, base, last))
        if rows:
            async with SessionLocal() as session, session.begin():
                new += (await ingest_readings(session, METER, rows, "replay")).rows_new
        lo = step_hi
    return new


async def main(once: bool) -> None:
    # Not __file__: piped in through `python -` (as above) the script has none.
    data_dir = Path(os.environ.get("REFIT_SEED_DIR") or "dataset")
    df = load_csv(data_dir / "CLEAN_House2.csv")
    async with SessionLocal() as session:
        days = await session.scalar(
            text("SELECT shift_days FROM etl.tb_watermark WHERE source = :s LIMIT 1"), {"s": SOURCE}
        )
        start = await session.scalar(
            text(
                "SELECT max(r.ts) FROM public.tb_reading r "
                "JOIN public.tb_series s USING (series_id) "
                "JOIN public.tb_meter m ON m.id = s.meter_id "
                "WHERE m.serial = :m AND s.kind = 'main'"
            ),
            {"m": METER},
        )
    if days is None or start is None:
        sys.exit("Seed REFIT first (alembic upgrade head with SEED_REFIT=1)")
    base = timedelta(days=days)

    now = datetime.now(UTC)
    print(f"gap {start} -> {now}: {await replay(df, base, start, now)} new readings", flush=True)
    while not once:
        await asyncio.sleep(TAIL_S)
        start, now = now, datetime.now(UTC)
        new = await replay(df, base, start, now)
        if new:
            print(f"{now:%H:%M:%S} +{new}", flush=True)


if __name__ == "__main__":
    asyncio.run(main("--once" in sys.argv))
