"""Load a REFIT CLEAN_House<N>.csv into energy.reading.

    python -m app.cli.load_refit --house N [--csv PATH] [--shift-days D] [--limit-rows R]
                                 [--batch-rows B] [--owner-email E]
"""

import argparse
import asyncio
import csv
import itertools
import math
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from ..services.ingest import IngestResult, ReadingRow, ingest_readings
from .provision_refit import CHANNELS, meter_serial, provision_house

SOURCE = "refit"
EXPECTED_COLUMNS = 13  # Time, Unix, Aggregate, Appliance1..9, Issues
BAD_CHANNEL = "<malformed csv row>"  # maps to no series, so ingest counts the row as bad
DEFAULT_CSV = "/data/CLEAN_REFIT_081116/CLEAN_House{house}.csv"


def csv_row_to_readings(row: list[str], shift: timedelta) -> list[ReadingRow]:
    """Ten readings (one per channel) for a CSV row, or one bad marker row if it is malformed.

    Malformed (wrong column count, non-numeric Unix or Issues) rows never crash the load: they
    become a single ReadingRow on an unmapped channel, so ingest counts them as rows_bad and the
    batch bookkeeping stays consistent. A non-numeric value in one channel becomes NaN, which
    ingest rejects for that channel only.
    """
    try:
        if len(row) != EXPECTED_COLUMNS:
            raise ValueError("column count")
        ts = datetime.fromtimestamp(int(row[1]), UTC) + shift
        quality = 1 if int(float(row[12])) == 1 else 0
    except (ValueError, OverflowError, OSError):
        return [ReadingRow(datetime(1970, 1, 1, tzinfo=UTC), BAD_CHANNEL, 0.0, 0)]
    out = []
    for channel, raw in zip(CHANNELS, row[2:12], strict=True):
        try:
            value = float(raw)
        except ValueError:
            value = math.nan
        out.append(ReadingRow(ts, channel, value, quality))
    return out


async def load_house(
    session: AsyncSession,
    house: int,
    csv_path: Path,
    shift_days: int = 0,
    batch_rows: int = 30_000,
    limit_rows: int | None = None,
) -> IngestResult:
    """Stream a REFIT CSV into the house's meter, committing after every chunk.

    The file is read row by row, never loaded whole. `batch_rows` CSV rows (ten readings each)
    go into one ingest_readings call, then the session commits, so a failure later in the file
    keeps the earlier chunks. `limit_rows` stops after that many CSV rows. The result sums
    rows_in/new/dup/bad over all chunks (batch_id is the last chunk's), and
    rows_in == rows_new + rows_dup + rows_bad holds for the total. The house must be provisioned
    (provision_house) and committed first; rows_in counts readings, so a clean row is ten.
    """
    shift = timedelta(days=shift_days)
    serial = meter_serial(house)
    total = IngestResult(batch_id=None, rows_in=0, rows_new=0, rows_dup=0, rows_bad=0)  # type: ignore[arg-type]
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader, None)  # header
        data = (r for r in reader if r)  # blank lines are not rows
        if limit_rows is not None:
            data = itertools.islice(data, limit_rows)
        while True:
            chunk = list(itertools.islice(data, batch_rows))
            if not chunk:
                break
            readings = [rd for row in chunk for rd in csv_row_to_readings(row, shift)]
            res = await ingest_readings(session, serial, readings, SOURCE)
            await session.commit()
            total.batch_id = res.batch_id
            total.rows_in += res.rows_in
            total.rows_new += res.rows_new
            total.rows_dup += res.rows_dup
            total.rows_bad += res.rows_bad
    return total


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m app.cli.load_refit", description=__doc__)
    p.add_argument("--house", type=int, required=True)
    p.add_argument("--csv", type=Path, help=f"default {DEFAULT_CSV}")
    p.add_argument("--shift-days", type=int, default=0)
    p.add_argument("--limit-rows", type=int)
    p.add_argument("--batch-rows", type=int, default=30_000)
    p.add_argument("--owner-email")
    return p


async def main(
    argv: list[str] | None = None,
    session_factory: Callable[[], AsyncSession] | None = None,
) -> int:
    args = _parser().parse_args(argv)
    if session_factory is None:
        from ..database import SessionLocal

        session_factory = SessionLocal
    path = args.csv or Path(DEFAULT_CSV.format(house=args.house))
    if not path.is_file():
        print(f"error: CSV not found: {path}", file=sys.stderr)
        return 2
    if args.batch_rows < 1:
        print("error: --batch-rows must be >= 1", file=sys.stderr)
        return 2
    owner = args.owner_email or f"refit-house{args.house}@example.invalid"
    async with session_factory() as session:
        try:
            await provision_house(session, args.house, owner)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        await session.commit()
        started = time.perf_counter()
        res = await load_house(
            session, args.house, path, args.shift_days, args.batch_rows, args.limit_rows
        )
        elapsed = time.perf_counter() - started
    rate = res.rows_in / elapsed if elapsed > 0 else 0.0
    print(
        f"house {args.house}: rows_in={res.rows_in} rows_new={res.rows_new} "
        f"rows_dup={res.rows_dup} rows_bad={res.rows_bad} "
        f"in {elapsed:.1f}s ({rate:,.0f} rows/s)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
