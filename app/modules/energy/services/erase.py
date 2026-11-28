import uuid
from datetime import datetime

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Series, device_estimate_table, reading_table

_STORES = (
    "SELECT materialization_hypertable_schema, materialization_hypertable_name "
    "FROM timescaledb_information.continuous_aggregates WHERE view_schema = 'public'"
)


# Tables that keep what was derived from readings, with the column that dates a row.
_DERIVED = (
    ("tb_device_cycle", "start_ts"),
    ("tb_alert", "ts"),
    ("tb_expect_hourly", "ts"),
    ("tb_forecast_snapshot", "generated_at"),
    ("tb_suggestion", "created_at"),
)


async def erase_home_history(db: AsyncSession, home_id: uuid.UUID, before: datetime) -> None:
    """Everything measured before `before` (a local midnight, so no day is cut), and what was
    derived from it, in the caller's transaction. The home, its devices and models stay."""
    await erase_home_readings(db, home_id, before)
    for table, ts in _DERIVED:
        await db.execute(
            text(f"DELETE FROM public.{table} WHERE home_id = :h AND {ts} < :t"),
            {"h": home_id, "t": before},
        )
    # A savings plan is its person's own: it stays, without the erased days' kWh.
    await db.execute(
        text(
            "UPDATE public.tb_savings_plan p SET days = COALESCE("
            "(SELECT jsonb_object_agg(key, value) FROM jsonb_each(p.days) "
            "WHERE key >= (CAST(:t AS timestamptz) AT TIME ZONE "
            "(SELECT timezone FROM public.tb_home WHERE id = :h))::date::text), '{}'::jsonb) "
            "WHERE p.home_id = :h"
        ),
        {"h": home_id, "t": before},
    )


async def erase_home_readings(
    db: AsyncSession, home_id: uuid.UUID, before: datetime | None = None
) -> None:
    """Deletes what was measured for a home's series (before `before`, or all), in the caller's
    transaction.

    The raw hypertables have no foreign keys, so deleting the home would leave them. The six
    continuous aggregates keep hourly and daily totals long after retention dropped the raw rows
    under them, so their stored rows go too (a refresh would not find them, and would recompute
    other homes' buckets). Call it before the home is deleted: the series ids come from the home.
    """
    # Compressed chunks are decompressed to delete rows; Timescale stops at 100000 rows by default,
    # far below a home's year of readings. Lifted for this transaction only.
    await db.execute(text("SET LOCAL timescaledb.max_tuples_decompressed_per_dml_transaction = 0"))
    series = select(Series.series_id).where(Series.home_id == home_id)
    for table in (reading_table, device_estimate_table):
        older = [] if before is None else [table.c.ts < before]
        await db.execute(delete(table).where(table.c.series_id.in_(series), *older))
    for schema, name in (await db.execute(text(_STORES))).all():
        older = "" if before is None else " AND bucket < :t"
        await db.execute(
            text(
                f'DELETE FROM "{schema}"."{name}" WHERE series_id IN '
                "(SELECT series_id FROM public.tb_series WHERE home_id = :h)" + older
            ),
            {"h": home_id} | ({} if before is None else {"t": before}),
        )
