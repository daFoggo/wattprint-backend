"""insight, copilot, knowledge and ops tables

Revision ID: 9e2c4a6b8d10
Revises: d7b3f9a2c6e4
"""

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

from alembic import op

revision = "9e2c4a6b8d10"
down_revision = "d7b3f9a2c6e4"
branch_labels = None
depends_on = None

UUID_PK = sa.text("gen_random_uuid()")
NOW = sa.text("now()")

# unaccent() is STABLE, so it cannot be used in a generated column directly. The wrapper pins
# the dictionary and search_path, which makes it safe to declare IMMUTABLE. The stdlib unaccent
# rules do not map the Vietnamese letters d-stroke (U+0111 / U+0110), hence the translate().
IMMUTABLE_UNACCENT = """
CREATE FUNCTION knowledge.immutable_unaccent(text) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
SET search_path = public, pg_catalog AS $$
    SELECT translate(
        public.unaccent('public.unaccent'::regdictionary, $1),
        U&'\\0111\\0110', 'dD'
    )
$$
"""

SERIES_DAILY_COVERAGE = """
CREATE VIEW ops.series_daily_coverage AS
SELECT series_id,
       (bucket AT TIME ZONE 'Asia/Ho_Chi_Minh')::date AS day,
       covered_minutes,
       1440 AS expected_minutes,
       covered_minutes::numeric / 1440 AS coverage
FROM energy.reading_1d
"""

STALE_SERIES = """
CREATE VIEW ops.stale_series AS
SELECT series_id,
       max(last_ts) AS last_ts,
       floor(extract(epoch FROM now() - max(last_ts)) / 60)::bigint AS minutes_since
FROM ops.ingest_checkpoint
GROUP BY series_id
HAVING max(last_ts) < now() - INTERVAL '60 minutes'
"""


def _uuid_pk() -> sa.Column:
    return sa.Column("id", sa.UUID, primary_key=True, server_default=UUID_PK)


def _fk(col: str, target: str, ondelete: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint([col], [target], ondelete=ondelete)


def _index(table: str, schema: str, col: str) -> None:
    op.create_index(f"ix_{table}_{col}", table, [col], schema=schema)


def _insight() -> None:
    op.execute(
        """
        CREATE TABLE insight.device_cycle (
            home_id uuid NOT NULL,
            device_id uuid NOT NULL,
            start_ts timestamptz NOT NULL,
            end_ts timestamptz NOT NULL,
            energy_wh double precision NOT NULL,
            peak_w real NOT NULL,
            CONSTRAINT pk_device_cycle PRIMARY KEY (device_id, start_ts),
            CONSTRAINT fk_device_cycle_home_id_home FOREIGN KEY (home_id)
                REFERENCES core.home (id) ON DELETE CASCADE,
            CONSTRAINT fk_device_cycle_device_id_device FOREIGN KEY (device_id)
                REFERENCES core.device (id) ON DELETE CASCADE,
            CONSTRAINT ck_device_cycle_range CHECK (end_ts > start_ts)
        )
        """
    )
    op.execute(
        "SELECT create_hypertable('insight.device_cycle', "
        "by_range('start_ts', INTERVAL '30 days'))"
    )
    op.create_index(
        "ix_device_cycle_home_start", "device_cycle",
        ["home_id", sa.text("start_ts DESC")], schema="insight",
    )

    op.create_table(
        "alert",
        _uuid_pk(),
        sa.Column("home_id", sa.UUID, nullable=False),
        sa.Column("device_id", sa.UUID),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.dialects.postgresql.JSONB, nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(16), nullable=False, server_default="open"),
        _fk("home_id", "core.home.id", "CASCADE"),
        _fk("device_id", "core.device.id", "SET NULL"),
        sa.CheckConstraint("severity IN ('info','warning','critical')", name="severity"),
        sa.CheckConstraint("status IN ('open','acknowledged','resolved')", name="status"),
        schema="insight",
    )
    op.create_index("ix_alert_home_ts", "alert", ["home_id", sa.text("ts DESC")],
                    schema="insight")
    _index("alert", "insight", "device_id")

    op.create_table(
        "forecast_snapshot",
        _uuid_pk(),
        sa.Column("home_id", sa.UUID, nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("horizon_date", sa.Date, nullable=False),
        sa.Column("kwh", sa.Numeric(12, 3), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("tier_cross_date", sa.Date),
        sa.Column("model_version", sa.Text, nullable=False),
        _fk("home_id", "core.home.id", "CASCADE"),
        sa.UniqueConstraint("home_id", "generated_at", "horizon_date"),
        schema="insight",
    )

    op.create_table(
        "cohort_stat",
        sa.Column("cohort_key", sa.Text, nullable=False),
        sa.Column("period", sa.Date, nullable=False),
        sa.Column("p10_w", sa.Numeric(10, 2), nullable=False),
        sa.Column("p33_w", sa.Numeric(10, 2), nullable=False),
        sa.Column("p66_w", sa.Numeric(10, 2), nullable=False),
        sa.Column("p90_w", sa.Numeric(10, 2), nullable=False),
        sa.Column("n_homes", sa.Integer, nullable=False),
        sa.PrimaryKeyConstraint("cohort_key", "period"),
        sa.CheckConstraint("n_homes >= 10", name="min_size"),
        schema="insight",
    )


def _copilot() -> None:
    op.create_table(
        "conversation",
        _uuid_pk(),
        sa.Column("home_id", sa.UUID, nullable=False),
        sa.Column("user_id", sa.UUID, nullable=False),
        sa.Column("title", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        _fk("home_id", "core.home.id", "CASCADE"),
        _fk("user_id", "users.id", "CASCADE"),
        schema="copilot",
    )
    _index("conversation", "copilot", "home_id")
    _index("conversation", "copilot", "user_id")

    op.create_table(
        "message",
        _uuid_pk(),
        sa.Column("conversation_id", sa.UUID, nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        _fk("conversation_id", "copilot.conversation.id", "CASCADE"),
        sa.CheckConstraint("role IN ('user','assistant','tool','system')", name="role"),
        schema="copilot",
    )
    _index("message", "copilot", "conversation_id")

    op.create_table(
        "tool_call",
        _uuid_pk(),
        sa.Column("message_id", sa.UUID, nullable=False),
        sa.Column("tool", sa.Text, nullable=False),
        sa.Column("input", sa.dialects.postgresql.JSONB, nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("sql_text", sa.Text),
        sa.Column("unit", sa.Text),
        sa.Column("duration_ms", sa.Integer),
        sa.Column("ok", sa.Boolean, nullable=False),
        _fk("message_id", "copilot.message.id", "CASCADE"),
        schema="copilot",
    )
    _index("tool_call", "copilot", "message_id")

    op.create_table(
        "suggestion",
        _uuid_pk(),
        sa.Column("home_id", sa.UUID, nullable=False),
        sa.Column("device_id", sa.UUID),
        sa.Column("alert_id", sa.UUID),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("expected_kwh", sa.Numeric(12, 3)),
        sa.Column("expected_amount", sa.Numeric(14, 2)),
        sa.Column("status", sa.String(16), nullable=False, server_default="proposed"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        _fk("home_id", "core.home.id", "CASCADE"),
        _fk("device_id", "core.device.id", "SET NULL"),
        _fk("alert_id", "insight.alert.id", "SET NULL"),
        sa.CheckConstraint(
            "status IN ('proposed','shown','accepted','dismissed','done')", name="status"
        ),
        schema="copilot",
    )
    for col in ("home_id", "device_id", "alert_id"):
        _index("suggestion", "copilot", col)

    op.create_table(
        "suggestion_feedback",
        _uuid_pk(),
        sa.Column("suggestion_id", sa.UUID, nullable=False),
        sa.Column("user_id", sa.UUID, nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("note", sa.Text),
        _fk("suggestion_id", "copilot.suggestion.id", "CASCADE"),
        _fk("user_id", "users.id", "CASCADE"),
        sa.CheckConstraint("action IN ('accept','ignore','done','dislike')", name="action"),
        schema="copilot",
    )
    _index("suggestion_feedback", "copilot", "suggestion_id")
    _index("suggestion_feedback", "copilot", "user_id")

    op.create_table(
        "savings_measure",
        sa.Column("suggestion_id", sa.UUID, primary_key=True),
        sa.Column("baseline_kwh", sa.Numeric(12, 3), nullable=False),
        sa.Column("actual_kwh", sa.Numeric(12, 3), nullable=False),
        sa.Column("weather_adjusted_kwh", sa.Numeric(12, 3)),
        sa.Column("method", sa.Text, nullable=False, server_default="M&V"),
        sa.Column("measured_at", sa.DateTime(timezone=True), nullable=False),
        _fk("suggestion_id", "copilot.suggestion.id", "CASCADE"),
        schema="copilot",
    )


def _knowledge() -> None:
    op.execute(IMMUTABLE_UNACCENT)
    op.create_table(
        "document",
        _uuid_pk(),
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
        schema="knowledge",
    )
    op.create_table(
        "chunk",
        sa.Column("id", sa.BigInteger, sa.Identity(always=False), primary_key=True),
        sa.Column("document_id", sa.UUID, nullable=False),
        sa.Column("ord", sa.Integer, nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column(
            "tsv", sa.dialects.postgresql.TSVECTOR,
            sa.Computed("to_tsvector('simple', knowledge.immutable_unaccent(body))",
                        persisted=True),
        ),
        sa.Column("embedding", Vector(1024), nullable=False),
        sa.Column("embedding_model", sa.Text, nullable=False),
        sa.Column("token_count", sa.Integer),
        _fk("document_id", "knowledge.document.id", "CASCADE"),
        sa.UniqueConstraint("document_id", "ord"),
        schema="knowledge",
    )
    op.create_index("ix_chunk_tsv", "chunk", ["tsv"], schema="knowledge",
                    postgresql_using="gin")
    op.create_index(
        "ix_chunk_embedding", "chunk", ["embedding"], schema="knowledge",
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
        postgresql_with={"m": 16, "ef_construction": 64},
    )


def _ops() -> None:
    op.create_table(
        "ingest_batch",
        _uuid_pk(),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("home_id", sa.UUID),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("rows_in", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("rows_new", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("rows_dup", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("rows_bad", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("status", sa.String(16), nullable=False, server_default="running"),
        sa.Column("note", sa.Text),
        _fk("home_id", "core.home.id", "SET NULL"),
        sa.CheckConstraint("status IN ('running','ok','failed')", name="status"),
        schema="ops",
    )
    _index("ingest_batch", "ops", "home_id")
    op.create_index("ix_ingest_batch_source_started", "ingest_batch",
                    ["source", sa.text("started_at DESC")], schema="ops")

    op.create_table(
        "ingest_checkpoint",
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("series_id", sa.Integer, nullable=False),
        sa.Column("last_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.PrimaryKeyConstraint("source", "series_id"),
        _fk("series_id", "energy.series.series_id", "CASCADE"),
        schema="ops",
    )
    _index("ingest_checkpoint", "ops", "series_id")
    op.execute(SERIES_DAILY_COVERAGE)
    op.execute(STALE_SERIES)


def upgrade() -> None:
    _insight()
    _copilot()
    _knowledge()
    _ops()


def downgrade() -> None:
    op.execute("DROP VIEW ops.stale_series")
    op.execute("DROP VIEW ops.series_daily_coverage")
    for schema, tables in (
        ("ops", ("ingest_checkpoint", "ingest_batch")),
        ("knowledge", ("chunk", "document")),
        ("copilot", ("savings_measure", "suggestion_feedback", "suggestion", "tool_call",
                     "message", "conversation")),
        ("insight", ("cohort_stat", "forecast_snapshot", "alert", "device_cycle")),
    ):
        for table in tables:
            op.drop_table(table, schema=schema)
    op.execute("DROP FUNCTION knowledge.immutable_unaccent(text)")
