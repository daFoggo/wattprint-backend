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
                    "extract(day FROM (j.config->>'drop_after')::interval)::int "
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
        oldest = await db.scalar(
            text(
                f"SELECT (min(r.{ts}) AT TIME ZONE h.timezone)::date FROM public.{relation} r "
                "JOIN public.tb_series s USING (series_id) "
                "JOIN public.tb_home h ON h.id = s.home_id WHERE h.id = :h GROUP BY h.timezone"
            ),
            {"h": home_id},
        )
        out.append((level, policies.get(relation), oldest))
    return out
