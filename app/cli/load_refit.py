"""Load a REFIT CLEAN_House<N>.csv into energy.reading.

    python -m app.cli.load_refit --house N [--csv PATH] [--shift-days D] [--limit-rows R]
                                 [--batch-rows B] [--owner-email E] [--allow-active-policies]

Loading history needs the retention and compression policies of energy.reading OFF
(`SELECT ops.set_policies(false)`) or dates shifted into their windows (`--shift-days`): the
migrated database has them ON, the retention job would delete REFIT data older than its window
and the compression job would compress chunks while they are being loaded. The CLI refuses
otherwise; `--allow-active-policies` overrides.
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

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..services.ingest import IngestResult, ReadingRow, ingest_readings
from .provision_refit import CHANNELS, METADATA, meter_serial, provision_house

SOURCE = "refit"
EXPECTED_COLUMNS = 13  # Time, Unix, Aggregate, Appliance1..9, Issues
BAD_CHANNEL = "<malformed csv row>"  # maps to no series, so ingest counts the row as bad
DEFAULT_CSV = "/data/CLEAN_REFIT_081116/CLEAN_House{house}.csv"


def first_timestamp(csv_path: Path, shift: timedelta) -> datetime | None:
    """Shifted timestamp of the first data row (None for an empty or malformed file)."""
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader, None)
        for row in reader:
            if row:
                try:
                    return datetime.fromtimestamp(int(row[1]), UTC) + shift
                except (IndexError, ValueError, OverflowError, OSError):
                    return None
    return None


async def policy_conflict(session: AsyncSession, first_ts: datetime | None) -> str | None:
    """Why loading data starting at first_ts would fight an active policy of energy.reading.

    A scheduled retention job deletes data older than its drop_after window and a scheduled
    compression job compresses chunks older than compress_after while the load is running.
    Returns a message, or None when no active policy would touch the data.
    """
    if first_ts is None:
        return None
    jobs = (
        await session.execute(
            text("SELECT proc_name, config->>'drop_after' AS drop_after, "
                 "config->>'compress_after' AS compress_after, "
                 "now() - CAST(coalesce(config->>'drop_after', config->>'compress_after') "
                 "AS interval) AS cutoff "
                 "FROM timescaledb_information.jobs WHERE hypertable_schema = 'energy' "
                 "AND hypertable_name = 'reading' AND scheduled "
                 "AND proc_name IN ('policy_retention', 'policy_compression') ORDER BY proc_name")
        )
    ).all()
    problems = []
    for j in jobs:
        if first_ts >= j.cutoff:
            continue
        if j.proc_name == "policy_retention":
            problems.append(
                f"the retention policy of energy.reading (drop_after {j.drop_after}) deletes data "
                f"older than {j.cutoff:%Y-%m-%d}")
        else:
            problems.append(
                f"the compression policy of energy.reading (compress_after {j.compress_after}) "
                f"compresses chunks older than {j.cutoff:%Y-%m-%d} while they are loaded")
    if not problems:
        return None
    return (
        f"the data starts at {first_ts:%Y-%m-%d}, but " + " and ".join(problems)
        + ". Move the dates into the window with --shift-days, or run "
        "SELECT ops.set_policies(false) before loading history "
        "(--allow-active-policies overrides this check)."
    )


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
            try:
                res = await ingest_readings(session, serial, readings, SOURCE)
            except Exception:
                # ingest_readings marked its batch row 'failed' (flushed only); commit it so the
                # audit survives. If the transaction is unusable, roll back instead.
                try:
                    await session.commit()
                except Exception:
                    await session.rollback()
                raise
            await session.commit()
            total.batch_id = res.batch_id
            total.rows_in += res.rows_in
            total.rows_new += res.rows_new
            total.rows_dup += res.rows_dup
            total.rows_bad += res.rows_bad
    return total


def _positive(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return value


def _days(text: str) -> int:
    value = int(text)
    if abs(value) > 36_500:
        raise argparse.ArgumentTypeError("must be within +-36500 days")
    return value


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m app.cli.load_refit", description=__doc__)
    p.add_argument("--house", type=int, required=True)
    p.add_argument("--csv", type=Path, help=f"default {DEFAULT_CSV}")
    p.add_argument("--shift-days", type=_days, default=0)
    p.add_argument("--limit-rows", type=_positive)
    p.add_argument("--batch-rows", type=_positive, default=30_000)
    p.add_argument("--owner-email")
    p.add_argument("--allow-active-policies", action="store_true",
                   help="load even if an active retention/compression policy would touch the data")
    return p


async def main(
    argv: list[str] | None = None,
    session_factory: Callable[[], AsyncSession] | None = None,
) -> int:
    args = _parser().parse_args(argv)
    if str(args.house) not in METADATA:
        print(f"error: unknown REFIT house {args.house}", file=sys.stderr)
        return 2
    path = args.csv or Path(DEFAULT_CSV.format(house=args.house))
    if not path.is_file():
        print(f"error: CSV not found: {path}", file=sys.stderr)
        return 2
    owner = args.owner_email or f"refit-house{args.house}@example.invalid"
    own_engine = session_factory is None
    if session_factory is None:
        from ..database import SessionLocal

        session_factory = SessionLocal
    try:
        async with session_factory() as session:
            try:
                await provision_house(session, args.house, owner)
            except ValueError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 2
            await session.commit()
            if not args.allow_active_policies:
                first_ts = first_timestamp(path, timedelta(days=args.shift_days))
                conflict = await policy_conflict(session, first_ts)
                if conflict:
                    print(f"error: {conflict}", file=sys.stderr)
                    return 2
            started = time.perf_counter()
            res = await load_house(
                session, args.house, path, args.shift_days, args.batch_rows, args.limit_rows
            )
            elapsed = time.perf_counter() - started
    finally:
        if own_engine:
            from ..database import engine

            await engine.dispose()
    rate = res.rows_in / elapsed if elapsed > 0 else 0.0
    print(
        f"house {args.house}: rows_in={res.rows_in} rows_new={res.rows_new} "
        f"rows_dup={res.rows_dup} rows_bad={res.rows_bad} "
        f"in {elapsed:.1f}s ({rate:,.0f} readings/s)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
