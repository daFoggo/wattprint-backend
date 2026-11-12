"""refresh the continuous aggregates over the REFIT House 2 seed

Revision ID: 5d0c9a3e7f21
Revises: b2183c4aca1c
"""

import os
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa

from alembic import op

revision = "5d0c9a3e7f21"
down_revision = "b2183c4aca1c"
branch_labels = None
depends_on = None


SOURCE = "refit/CLEAN_House2.csv"
VIEWS = ("public.reading_1m", "public.reading_1h", "public.reading_1d")  # dependency order
DAY = timedelta(days=1)
ORIGIN = datetime(2000, 1, 1, 17, tzinfo=UTC)  # 17:00 UTC = local midnight (ICT, no DST)


def _floor(ts: datetime) -> datetime:
    return ORIGIN + (ts - ORIGIN) // DAY * DAY


def windows(lo: datetime, hi: datetime, now: datetime) -> list[tuple[datetime, datetime]]:
    """Local midnight to midnight, at most 31 days each, never into today's still-open bucket
    (reading_1d's policy stops an hour before now, so a partial today would stay stale)."""
    lo, hi = _floor(lo), min(_floor(hi) + DAY, _floor(now))
    out = []
    while lo < hi:
        # The last window takes the remainder (1 to 31 days): a window under one bucket is refused.
        step = hi if hi - lo <= 31 * DAY else lo + 30 * DAY
        out.append((lo, step))
        lo = step
    return out


def upgrade() -> None:
    """The seed loads raw readings only. The refresh policies cover the last 7/30/60 days and their
    watermark is already past the history, so without this the seed is invisible to reading_*."""
    if os.environ.get("SEED_REFIT", "1") == "0":  # test databases migrate without seed data
        return
    conn = op.get_bind()
    span = conn.execute(
        sa.text(
            "SELECT min(range_from), max(range_to) FROM etl.tb_watermark "
            "WHERE source = :s AND status = 'done'"
        ),
        {"s": SOURCE},
    ).one()
    if span[0] is None:
        return
    # refresh_continuous_aggregate cannot run inside a transaction block.
    with op.get_context().autocommit_block():
        for lo, hi in windows(span[0], span[1], datetime.now(UTC)):
            for view in VIEWS:
                conn.execute(
                    sa.text(
                        "CALL refresh_continuous_aggregate("
                        "CAST(:v AS regclass), CAST(:lo AS timestamptz), CAST(:hi AS timestamptz))"
                    ),
                    {"v": view, "lo": lo, "hi": hi},
                )


def downgrade() -> None:
    pass  # materialized rows are derived data; the policies keep them
