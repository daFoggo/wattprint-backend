"""copilot and knowledge tables (pending AI schema design)

Revision ID: 9e2c4a6b8d10
Revises: c1d4e8a2b6f0
"""

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

from alembic import op

revision = "9e2c4a6b8d10"
down_revision = "c1d4e8a2b6f0"
branch_labels = None
depends_on = None

NOW = sa.text("now()")

IMMUTABLE_UNACCENT = """
CREATE FUNCTION public.immutable_unaccent(text) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
SET search_path = pg_catalog, public AS $$
    SELECT public.unaccent('public.unaccent'::regdictionary, $1)
$$
"""

def _int_pk() -> sa.Column:
    return sa.Column("id", sa.Integer, sa.Identity(always=False), primary_key=True)


def _fk(col: str, target: str, ondelete: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint([col], [target], ondelete=ondelete)

def _copilot() -> None:
    op.create_table(
        "tb_suggestion",
        _int_pk(),
        sa.Column("home_id", sa.Integer, nullable=False),
        sa.Column("device_id", sa.Integer),
        sa.Column("alert_id", sa.Integer),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("expected_kwh", sa.Numeric(12, 3)),
        sa.Column("expected_amount", sa.Numeric(14, 2)),
        sa.Column("status", sa.String(16), nullable=False, server_default="proposed"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        _fk("home_id", "public.tb_home.id", "CASCADE"),
        _fk("device_id", "public.tb_device.id", "SET NULL"),
        _fk("alert_id", "public.tb_alert.id", "SET NULL"),
        sa.CheckConstraint(
            "status IN ('proposed','shown','accepted','dismissed','done')", name="status"
        ),
        schema="public",
    )
    op.create_table(
        "tb_suggestion_feedback",
        _int_pk(),
        sa.Column("suggestion_id", sa.Integer, nullable=False),
        sa.Column("user_id", sa.Integer, nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("note", sa.Text),
        _fk("suggestion_id", "public.tb_suggestion.id", "CASCADE"),
        _fk("user_id", "public.tb_users.id", "CASCADE"),
        sa.CheckConstraint("action IN ('accept','ignore','done','dislike')", name="action"),
        schema="public",
    )
    op.create_table(
        "tb_savings_measure",
        sa.Column("suggestion_id", sa.Integer, primary_key=True),
        sa.Column("baseline_kwh", sa.Numeric(12, 3), nullable=False),
        sa.Column("actual_kwh", sa.Numeric(12, 3), nullable=False),
        sa.Column("weather_adjusted_kwh", sa.Numeric(12, 3)),
        sa.Column("method", sa.Text, nullable=False, server_default="M&V"),
        sa.Column("measured_at", sa.DateTime(timezone=True), nullable=False),
        _fk("suggestion_id", "public.tb_suggestion.id", "CASCADE"),
        schema="public",
    )


def _knowledge() -> None:
    op.execute(IMMUTABLE_UNACCENT)
    op.create_table(
        "tb_document",
        _int_pk(),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("doc_type", sa.String(16), nullable=False),
        sa.Column("lang", sa.Text, nullable=False, server_default="vi"),
        sa.Column("source_url", sa.Text),
        sa.Column("version", sa.Text),
        sa.Column("license_note", sa.Text),
        sa.Column("published_at", sa.Date),
        sa.CheckConstraint(
            "doc_type IN ('standard','guide','tariff','expert_rule','other')", name="doc_type"
        ),
        schema="public",
    )
    op.create_table(
        "tb_chunk",
        sa.Column("id", sa.BigInteger, sa.Identity(always=False), primary_key=True),
        sa.Column("document_id", sa.Integer, nullable=False),
        sa.Column("ord", sa.Integer, nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column(
            "tsv",
            sa.dialects.postgresql.TSVECTOR,
            sa.Computed(
                "to_tsvector('simple', public.immutable_unaccent(body))", persisted=True
            ),
        ),
        sa.Column("embedding", Vector(1024), nullable=False),
        sa.Column("embedding_model", sa.Text, nullable=False),
        sa.Column("token_count", sa.Integer),
        _fk("document_id", "public.tb_document.id", "CASCADE"),
        sa.UniqueConstraint("document_id", "ord"),
        schema="public",
    )

def upgrade() -> None:
    _copilot()
    _knowledge()


def downgrade() -> None:
    for table in ("tb_chunk", "tb_document"):
        op.drop_table(table, schema="public")
    op.execute("DROP FUNCTION public.immutable_unaccent(text)")
    for table in (
        "tb_savings_measure",
        "tb_suggestion_feedback",
        "tb_suggestion",
    ):
        op.drop_table(table, schema="public")
