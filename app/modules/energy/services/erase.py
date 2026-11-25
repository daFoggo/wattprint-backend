import uuid

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Series, device_estimate_table, reading_table

_STORES = (
    "SELECT materialization_hypertable_schema, materialization_hypertable_name "
    "FROM timescaledb_information.continuous_aggregates WHERE view_schema = 'public'"
)


async def erase_home_readings(db: AsyncSession, home_id: uuid.UUID) -> None:
    """Deletes everything measured for a home's series, in the caller's transaction.

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
        await db.execute(delete(table).where(table.c.series_id.in_(series)))
    for schema, name in (await db.execute(text(_STORES))).all():
        await db.execute(
            text(
                f'DELETE FROM "{schema}"."{name}" WHERE series_id IN '
                "(SELECT series_id FROM public.tb_series WHERE home_id = :h)"
            ),
            {"h": home_id},
        )
