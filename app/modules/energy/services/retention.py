import uuid
from datetime import date

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# level -> the relation a home's oldest value is read from
_LEVELS = (("raw", "tb_reading", "ts"),) + tuple(
    (res, f"reading_{res}", "bucket") for res in ("1m", "1h", "1d")
)


async def kept_history(db: AsyncSession, home_id: uuid.UUID) -> list[tuple[str, int | None, date]]:
    """(level, days the retention policy keeps it or None, the home's oldest local day or None)."""
    policies = dict(
        (
            await db.execute(
                text(
                    "SELECT COALESCE(c.view_name, j.hypertable_name), "
                    "(extract(epoch FROM (j.config->>'drop_after')::interval) / 86400)::int "
                    "FROM timescaledb_information.jobs j "
                    "LEFT JOIN timescaledb_information.continuous_aggregates c "
                    "ON c.materialization_hypertable_name = j.hypertable_name "
                    "WHERE j.proc_name = 'policy_retention'"
                )
            )
        ).all()
    )
    out = []
    for level, relation, ts in _LEVELS:
        # shortcut: the one screen query on raw `tb_reading` (the oldest kept raw row is what the
        # page reports): a min over this home's series ids, answered by their index.
        oldest = await db.scalar(
            text(
                f"SELECT (q.m AT TIME ZONE h.timezone)::date FROM (SELECT min({ts}) AS m "
                f"FROM public.{relation} WHERE series_id = ANY (ARRAY(SELECT series_id "
                "FROM public.tb_series WHERE home_id = :h))) q "
                "JOIN public.tb_home h ON h.id = :h"
            ),
            {"h": home_id},
        )
        out.append((level, policies.get(relation), oldest))
    return out
