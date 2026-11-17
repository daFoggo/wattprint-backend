"""etl.tb_watermark on every database, not only when the House 2 seed runs

Revision ID: 3e8b6d2f9a14
Revises: 7c1e5a9d3b20
"""

from alembic import op

revision = "3e8b6d2f9a14"
down_revision = "7c1e5a9d3b20"
branch_labels = None
depends_on = None

# Same DDL as the seed revision b2183c4aca1c (IF NOT EXISTS), which only creates it when it seeds.
# scripts/seed_demo_homes.py and scripts/replay_refit.py keep each REFIT meter's time shift here.
DDL = (
    "CREATE SCHEMA IF NOT EXISTS etl",
    """
    CREATE TABLE IF NOT EXISTS etl.tb_watermark (
        source      text        NOT NULL,
        segment     text        NOT NULL,
        shift_days  integer     NOT NULL,
        range_from  timestamptz NOT NULL,
        range_to    timestamptz NOT NULL,
        last_ts     timestamptz,
        rows_loaded bigint      NOT NULL DEFAULT 0,
        status      text        NOT NULL DEFAULT 'pending',
        error       text,
        updated_at  timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT pk_watermark PRIMARY KEY (source, segment),
        CONSTRAINT ck_watermark_status CHECK (status IN ('pending', 'running', 'done', 'failed'))
    )
    """,
)


def upgrade() -> None:
    for ddl in DDL:
        op.execute(ddl)


def downgrade() -> None:
    pass  # the seed revision owns the table when it seeded; dropping here could lose its rows
