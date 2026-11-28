"""Tiered retention (privacy spec R1.1). A script, not a migration: the api container runs
`alembic upgrade head` on every start, and what these policies drop cannot be got back.

    docker compose exec -T api python -m scripts.apply_retention           # dry run, read-only
    docker compose exec -T api python -m scripts.apply_retention --apply   # IRREVERSIBLE
    docker compose exec -T api python -m scripts.apply_retention --revert  # today's policies back

Revert restores the policies, not the rows already dropped. `public.set_policies(false)` (used
before loading old data) does not remove the _1h, _1d and tb_device_cycle policies: run --revert
first. The nightly cleanup of ordinary tables is separate (RETENTION_TIERS=true, insight worker).
"""

import argparse
import asyncio
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from app.config import settings

# relation -> (time column, days kept today or None, days kept with the tiers)
RELATIONS = {
    "tb_reading": ("ts", 400, 30),
    "tb_device_estimate": ("ts", 400, 30),
    "reading_1m": ("bucket", 400, 90),
    "device_estimate_1m": ("bucket", 400, 90),
    "reading_1h": ("bucket", None, 400),
    "device_estimate_1h": ("bucket", None, 400),
    "reading_1d": ("bucket", None, 800),
    "device_estimate_1d": ("bucket", None, 800),
    "tb_device_cycle": ("start_ts", None, 90),
}


@dataclass
class Row:
    relation: str
    now_days: int | None
    new_days: int
    chunks: int  # whole chunks past the new age: what drop_chunks takes
    total: int
    rows: int
    before: datetime | None  # everything older than this goes


async def dry_run(conn: AsyncConnection) -> list[Row]:
    out = []
    for relation, (column, _, days) in RELATIONS.items():
        # a continuous aggregate's chunks and rows are those of its materialization hypertable
        schema, table = (
            await conn.execute(
                text(
                    "SELECT materialization_hypertable_schema, materialization_hypertable_name "
                    "FROM timescaledb_information.continuous_aggregates "
                    "WHERE view_schema = 'public' AND view_name = :r"
                ),
                {"r": relation},
            )
        ).first() or ("public", relation)
        chunks = (
            await conn.execute(
                text(
                    "SELECT count(*) AS total, "
                    "count(*) FILTER (WHERE range_end <= now() - make_interval(days => :d)) AS n, "
                    "max(range_end) FILTER (WHERE range_end <= now() - make_interval(days => :d)) "
                    "AS before FROM timescaledb_information.chunks "
                    "WHERE hypertable_schema = :s AND hypertable_name = :t"
                ),
                {"d": days, "s": schema, "t": table},
            )
        ).one()
        rows = 0
        if chunks.before:
            rows = await conn.scalar(
                text(f'SELECT count(*) FROM "{schema}"."{table}" WHERE {column} < :b'),
                {"b": chunks.before},
            )
        current = await conn.scalar(
            text(
                "SELECT (extract(epoch FROM (config->>'drop_after')::interval) / 86400)::int "
                "FROM timescaledb_information.jobs WHERE proc_name = 'policy_retention' "
                # jobs list an aggregate's policy under its view or its materialization
                "AND hypertable_name IN (:r, :t)"
            ),
            {"r": relation, "t": table},
        )
        out.append(Row(relation, current, days, chunks.n, chunks.total, rows, chunks.before))
    return out


async def _set(conn: AsyncConnection, relation: str, days: int | None) -> None:
    name = f"public.{relation}"
    await conn.execute(
        text("SELECT remove_retention_policy(CAST(:r AS regclass), if_exists => true)"), {"r": name}
    )
    if days is not None:
        await conn.execute(
            text(
                "SELECT add_retention_policy(CAST(:r AS regclass), "
                "drop_after => make_interval(days => :d))"
            ),
            {"r": name, "d": days},
        )


async def apply(conn: AsyncConnection) -> None:
    for relation, (_, _, days) in RELATIONS.items():
        await _set(conn, relation, days)


async def revert(conn: AsyncConnection) -> None:
    for relation, (_, days, _) in RELATIONS.items():
        await _set(conn, relation, days)


async def main(args: argparse.Namespace) -> None:
    engine = create_async_engine(settings.database_url)
    print(f"database: {engine.url.database}")
    try:
        async with engine.begin() as conn:  # one transaction: all policies change or none
            if args.apply:
                await apply(conn)
                print("tiered retention policies applied")
            elif args.revert:
                await revert(conn)
                print("earlier retention policies restored")
            else:
                await conn.execute(text("SET TRANSACTION READ ONLY"))
                print("dry run, nothing changed")
                print(f"{'relation':20} {'now':>5} {'new':>5} {'chunks':>9} {'rows':>12}  before")
                for r in await dry_run(conn):
                    print(
                        f"{r.relation:20} {r.now_days or '-':>5} {r.new_days:>5} "
                        f"{f'{r.chunks}/{r.total}':>9} {r.rows:>12}  "
                        f"{r.before.date() if r.before else '-'}"
                    )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="set the policies (irreversible drops)")
    mode.add_argument("--revert", action="store_true", help="restore the earlier policies")
    asyncio.run(main(parser.parse_args()))
