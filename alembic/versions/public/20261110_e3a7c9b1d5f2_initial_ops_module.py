"""initial ops module: ingestion batches and checkpoints

Revision ID: e3a7c9b1d5f2
Revises: 9e2c4a6b8d10
"""

import sqlalchemy as sa

from alembic import op

revision = "e3a7c9b1d5f2"
down_revision = "9e2c4a6b8d10"
branch_labels = None
depends_on = None

NOW = sa.text("now()")
UUID7 = sa.text("uuidv7()")

STALE_SERIES = """
CREATE VIEW public.stale_series AS
SELECT series_id,
       max(last_ts) AS last_ts,
       floor(extract(epoch FROM now() - max(last_ts)) / 60)::bigint AS minutes_since
FROM public.tb_ingest_checkpoint
GROUP BY series_id
HAVING max(last_ts) < now() - INTERVAL '60 minutes'
"""

STALE_SERIES_COMMENT = (
    "Series whose newest ingest checkpoint is older than 60 minutes. Multi-source rule: "
    "max(last_ts) across sources, so a series is stale only if every source is stale. "
    "Limitation: built from public.tb_ingest_checkpoint only; a series that never reported has no "
    "checkpoint and is not listed."
)

def _comment_view(view: str, text: str) -> None:
    # COMMENT does not accept bind parameters, so the literal is quoted by hand.
    op.execute(sa.text("COMMENT ON VIEW " + view + " IS '" + text.replace("'", "''") + "'"))


def _uuid_pk() -> sa.Column:
    return sa.Column("id", sa.Uuid, server_default=UUID7, primary_key=True)


def _fk(col: str, target: str, ondelete: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint([col], [target], ondelete=ondelete)

def _ops() -> None:
    op.create_table(
        "tb_ingest_batch",
        _uuid_pk(),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("home_id", sa.Uuid),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("rows_in", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("rows_new", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("rows_dup", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("rows_bad", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("status", sa.String(16), nullable=False, server_default="running"),
        sa.Column("note", sa.Text),
        _fk("home_id", "public.tb_home.id", "SET NULL"),
        sa.CheckConstraint("status IN ('running','ok','failed')", name="status"),
        schema="public",
    )
    op.create_table(
        "tb_ingest_checkpoint",
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("series_id", sa.Uuid, nullable=False),
        sa.Column("last_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.PrimaryKeyConstraint("source", "series_id"),
        _fk("series_id", "public.tb_series.series_id", "CASCADE"),
        schema="public",
    )

    op.execute(STALE_SERIES)
    _comment_view("public.stale_series", STALE_SERIES_COMMENT)


def upgrade() -> None:
    _ops()


def downgrade() -> None:
    op.execute("DROP VIEW public.stale_series")
    for table in ("tb_ingest_checkpoint", "tb_ingest_batch"):
        op.drop_table(table, schema="public")
