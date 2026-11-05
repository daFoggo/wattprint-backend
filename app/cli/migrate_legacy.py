"""Move the data of the previous demo schema into the energy schema.

The previous demo kept three tables of watts, keyed by (house_id, ts[, appliance]):

    aggregate_power  whole-home power, what the meter sends
    appliance_power  NILMFormer estimates per appliance
    appliance_truth  plug sub-meter readings per appliance (ground truth), replayed days only

Export them to CSV with a header (see docs/nilm-simulation.md), then:

    python -m app.cli.migrate_legacy --dump DIR --owner-email E [--house N] [--replay-end DATE]
                                     [--dry-run]

All old houses are copies of the same REFIT house (the demo replayed its CSV under other ids), so
they are merged into the REFIT home of the account `--owner-email` (register it first). The
highest old house id wins on a minute they share. The aggregate and the sub-meters become
`energy.reading` rows (through `ingest_readings`), the estimates `energy.device_estimate` rows of
a new `energy.inference_run` (through `ingest_estimates`).

Timestamps move like in the replay (see app/services/simulation.py): the raw tables drop data
older than 400 days, so the last source day is stored under `--replay-end` (default yesterday)
and the earlier days under the days before it. What the home already stores for those days
(readings of the main, plug and estimate series) is replaced. The continuous aggregates are
refreshed over the loaded range at the end.
"""

import argparse
import asyncio
import csv
import datetime as dt
import sys
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..cli.provision_refit import METADATA, meter_serial, provision_house
from ..ml import MODEL_NAME, MODEL_VERSION
from ..models import InferenceRun, User
from ..services.disaggregation import local_day_start, local_today, main_series
from ..services.ingest import ReadingRow, ingest_estimates, ingest_readings
from ..services.simulation import appliance_items, replay_shift

SOURCE = "legacy-migration"  # ops.ingest_batch.source of the migrated readings
CHUNK = 30_000
MAX_AGE_DAYS = 390  # energy.reading drops data older than 400 days (ops.set_policies)
FILES = ("aggregate_power", "appliance_power", "appliance_truth")


@dataclass
class Legacy:
    """The old tables merged over the old houses: key -> watts."""

    aggregate: dict[dt.datetime, float] = field(default_factory=dict)
    estimates: dict[tuple[dt.datetime, str], float] = field(default_factory=dict)
    truth: dict[tuple[dt.datetime, str], float] = field(default_factory=dict)
    houses: list[int] = field(default_factory=list)


@dataclass(frozen=True)
class Plan:
    first_day: dt.date  # first and last source day (UTC)
    last_day: dt.date
    first_target: dt.date  # where they are stored (Asia/Ho_Chi_Minh days)
    last_target: dt.date
    shift: dt.timedelta


def parse_ts(value: str) -> dt.datetime:
    """A timestamptz as psql prints it ('2015-01-05 00:00:00+00'), in UTC."""
    v = value.strip()
    if len(v) > 3 and v[-3] in "+-" and v[-2:].isdigit():  # '+00' -> '+00:00'
        v += ":00"
    ts = dt.datetime.fromisoformat(v)
    if ts.tzinfo is None:
        raise ValueError(f"timestamp without a time zone: {value!r}")
    return ts.astimezone(dt.UTC)


def _rows(path: Path) -> Iterator[dict[str, str]]:
    with open(path, newline="", encoding="utf-8") as f:
        yield from csv.DictReader(f)


def read_legacy(dump: Path) -> Legacy:
    """Read the three CSVs of `dump`; the highest house id wins on a shared (ts, appliance)."""
    legacy = Legacy()
    houses: set[int] = set()

    def ordered(name: str) -> list[dict[str, str]]:
        rows = list(_rows(dump / f"{name}.csv"))
        houses.update(int(r["house_id"]) for r in rows)
        return sorted(rows, key=lambda r: int(r["house_id"]))  # stable: later houses overwrite

    for r in ordered("aggregate_power"):
        legacy.aggregate[parse_ts(r["ts"])] = float(r["watts"])
    for r in ordered("appliance_power"):
        legacy.estimates[(parse_ts(r["ts"]), r["appliance"])] = float(r["watts"])
    for r in ordered("appliance_truth"):
        legacy.truth[(parse_ts(r["ts"]), r["appliance"])] = float(r["watts"])
    legacy.houses = sorted(houses)
    return legacy


def make_plan(legacy: Legacy, replay_end: dt.date, today: dt.date) -> Plan:
    """Source days -> stored days. Raises ValueError when the result would not be kept."""
    stamps = [*legacy.aggregate, *(k[0] for k in legacy.estimates), *(k[0] for k in legacy.truth)]
    if not stamps:
        raise ValueError("the dump holds no data")
    first, last = min(stamps).date(), max(stamps).date()  # UTC days
    if replay_end > today:
        raise ValueError(f"--replay-end {replay_end} is in the future (today is {today})")
    first_target = replay_end - (last - first)
    if first_target < today - dt.timedelta(days=MAX_AGE_DAYS):
        raise ValueError(
            f"the data would start on {first_target}, older than the {MAX_AGE_DAYS} days the "
            "retention policy keeps; use a later --replay-end"
        )
    return Plan(first, last, first_target, replay_end, replay_shift(last, replay_end))


def _batches[T](items: Sequence[T], size: int) -> Iterator[Sequence[T]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


async def migrate(
    session: AsyncSession, legacy: Legacy, plan: Plan, house: int, owner_email: str
) -> dict[str, int]:
    """Load `legacy` into the REFIT home of the account; returns the counters to print."""
    user = await session.scalar(select(User).where(User.email == owner_email.lower()))
    if user is None:
        raise LookupError(f"no account {owner_email!r}: register it first (POST /auth/register)")
    home_id = await provision_house(session, house, owner_email)
    await session.commit()
    items = await appliance_items(session, home_id)
    if not items:
        raise ValueError(f"REFIT house {house} has none of the appliances the model covers")
    main = await main_series(session, home_id)
    by_type = {i.type: i for i in items}

    start = local_day_start(plan.first_target)
    end = local_day_start(plan.last_target) + dt.timedelta(days=1)
    run = InferenceRun(
        home_id=home_id,
        model_name=MODEL_NAME,
        model_version=MODEL_VERSION,
        window_start=start,
        window_end=end,
        status="running",
    )
    session.add(run)
    await session.flush()
    run_id = run.run_id
    await session.commit()

    counters = dict.fromkeys(
        ("run_id", "readings", "readings_new", "estimates", "skipped_appliance"), 0
    )
    counters["run_id"] = run_id
    try:
        window = {"a": start, "b": end}
        await session.execute(
            text("DELETE FROM energy.reading WHERE series_id = ANY(:ids) AND ts >= :a AND ts < :b"),
            {"ids": [main, *(i.plug_series for i in items)], **window},
        )
        await session.execute(
            text(
                "DELETE FROM energy.device_estimate "
                "WHERE series_id = ANY(:ids) AND ts >= :a AND ts < :b"
            ),
            {"ids": [i.estimate_series for i in items], **window},
        )
        await session.commit()

        readings = [
            ReadingRow(ts + plan.shift, "Aggregate", w) for ts, w in legacy.aggregate.items()
        ]
        estimates: list[tuple[dt.datetime, int, float]] = []
        for (ts, appliance), w in legacy.truth.items():
            item = by_type.get(appliance)
            if item is None:
                counters["skipped_appliance"] += 1
            else:
                readings.append(ReadingRow(ts + plan.shift, item.channel, w))
        for (ts, appliance), w in legacy.estimates.items():
            item = by_type.get(appliance)
            if item is None:
                counters["skipped_appliance"] += 1
            else:
                estimates.append((ts + plan.shift, item.estimate_series, w))
        readings.sort(key=lambda r: r.ts)
        estimates.sort(key=lambda e: e[0])

        meter = meter_serial(house)
        for chunk in _batches(readings, CHUNK):
            res = await ingest_readings(session, meter, chunk, SOURCE)
            await session.commit()
            counters["readings"] += res.rows_in
            counters["readings_new"] += res.rows_new
        for chunk in _batches(estimates, CHUNK):
            counters["estimates"] += await ingest_estimates(session, run_id, chunk)
            await session.commit()
        status = "ok"
    except BaseException:
        await session.rollback()
        status = "failed"
        raise
    finally:
        await session.execute(
            text(
                "UPDATE energy.inference_run SET status = :s, finished_at = now() WHERE run_id = :r"
            ),
            {"s": status, "r": run_id},
        )
        await session.commit()
    return counters


def _describe(legacy: Legacy, plan: Plan) -> str:
    return (
        f"old houses {legacy.houses}: {len(legacy.aggregate)} aggregate minutes, "
        f"{len(legacy.estimates)} estimates, {len(legacy.truth)} sub-meter readings\n"
        f"source days {plan.first_day} .. {plan.last_day} (UTC) -> stored under "
        f"{plan.first_target} .. {plan.last_target} (Asia/Ho_Chi_Minh), "
        f"shift {plan.shift}"
    )


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m app.cli.migrate_legacy", description=__doc__)
    p.add_argument("--dump", type=Path, required=True, help="folder with the three CSV files")
    p.add_argument("--owner-email", required=True, help="registered account that owns the home")
    p.add_argument("--house", type=int, default=2, help="REFIT house the old data comes from")
    p.add_argument(
        "--replay-end",
        type=dt.date.fromisoformat,
        help="day the last source day is stored under (default: yesterday)",
    )
    p.add_argument("--dry-run", action="store_true", help="print the plan, write nothing")
    return p


async def main(
    argv: list[str] | None = None,
    session_factory: Callable[[], AsyncSession] | None = None,
) -> int:
    args = _parser().parse_args(argv)
    if str(args.house) not in METADATA:
        print(f"error: unknown REFIT house {args.house}", file=sys.stderr)
        return 2
    missing = [f"{n}.csv" for n in FILES if not (args.dump / f"{n}.csv").is_file()]
    if missing:
        print(f"error: not found in {args.dump}: {', '.join(missing)}", file=sys.stderr)
        return 2
    try:
        legacy = read_legacy(args.dump)
        today = local_today()
        plan = make_plan(legacy, args.replay_end or today - dt.timedelta(days=1), today)
    except (ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(_describe(legacy, plan))
    if args.dry_run:
        return 0

    from ..database import SessionLocal, engine
    from ..services.aggregates import backfill_aggregates

    session_factory = session_factory or SessionLocal
    try:
        async with session_factory() as session:
            try:
                counters = await migrate(session, legacy, plan, args.house, args.owner_email)
            except (LookupError, ValueError) as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 2
        start = local_day_start(plan.first_target)
        end = local_day_start(plan.last_target) + dt.timedelta(days=1)
        async with engine.execution_options(isolation_level="AUTOCOMMIT").connect() as conn:
            skipped = await backfill_aggregates(conn, start, end)
    finally:
        await engine.dispose()
    print(
        f"run {counters['run_id']}: {counters['readings']} readings sent "
        f"({counters['readings_new']} new), {counters['estimates']} estimates written, "
        f"{counters['skipped_appliance']} rows of appliances the home does not track skipped"
    )
    for window in skipped:
        print(f"warning: aggregate {window.view} not refreshed {window.from_ts}..{window.to_ts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
