"""energy tables, hypertables and ops.set_policies

Revision ID: b9d2e6f0a384
Revises: 7a91e4d2b6c8
"""

import sqlalchemy as sa

from alembic import op

revision = "b9d2e6f0a384"
down_revision = "7a91e4d2b6c8"
branch_labels = None
depends_on = None

# Task 4 extends this body with CREATE OR REPLACE FUNCTION.
SET_POLICIES = """
CREATE FUNCTION ops.set_policies(enabled boolean) RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
    IF enabled THEN
        PERFORM add_compression_policy('energy.reading', INTERVAL '2 days', if_not_exists => true);
        PERFORM add_compression_policy('energy.device_estimate', INTERVAL '2 days',
                                       if_not_exists => true);
        PERFORM add_retention_policy('energy.reading', INTERVAL '400 days', if_not_exists => true);
        PERFORM add_retention_policy('energy.device_estimate', INTERVAL '400 days',
                                     if_not_exists => true);
    ELSE
        PERFORM remove_compression_policy('energy.reading', if_exists => true);
        PERFORM remove_compression_policy('energy.device_estimate', if_exists => true);
        PERFORM remove_retention_policy('energy.reading', if_exists => true);
        PERFORM remove_retention_policy('energy.device_estimate', if_exists => true);
    END IF;
END
$$
"""


def upgrade() -> None:
    op.create_table(
        "series",
        sa.Column("series_id", sa.Integer, sa.Identity(always=False), primary_key=True),
        sa.Column("home_id", sa.UUID, nullable=False),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("device_id", sa.UUID),
        sa.Column("meter_id", sa.UUID),
        sa.Column("source_channel", sa.Text),
        sa.Column("metric", sa.Text, nullable=False),
        sa.Column("unit", sa.Text, nullable=False),
        sa.ForeignKeyConstraint(["home_id"], ["core.home.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["device_id"], ["core.device.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["meter_id"], ["core.meter.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["metric"], ["catalog.metric.event_type"]),
        sa.CheckConstraint("kind IN ('main','plug','device')", name="kind"),
        sa.CheckConstraint("kind <> 'main' OR device_id IS NULL", name="main_has_no_device"),
        sa.CheckConstraint(
            "kind NOT IN ('plug','device') OR device_id IS NOT NULL",
            name="device_kinds_need_device",
        ),
        sa.UniqueConstraint(
            "home_id", "kind", "device_id", "metric",
            name="uq_series_home_kind_device_metric",
            postgresql_nulls_not_distinct=True,
        ),
        schema="energy",
    )
    op.create_index(
        "ix_series_meter_channel", "series", ["meter_id", "source_channel"], unique=True,
        schema="energy",
        postgresql_where=sa.text("meter_id IS NOT NULL AND source_channel IS NOT NULL"),
    )
    op.create_index("ix_series_device_id", "series", ["device_id"], schema="energy")

    op.create_table(
        "inference_run",
        sa.Column("run_id", sa.Integer, sa.Identity(always=False), primary_key=True),
        sa.Column("home_id", sa.UUID, nullable=False),
        sa.Column("model_name", sa.Text, nullable=False),
        sa.Column("model_version", sa.Text, nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.Text, nullable=False, server_default="running"),
        sa.ForeignKeyConstraint(["home_id"], ["core.home.id"], ondelete="CASCADE"),
        sa.CheckConstraint("status IN ('running','ok','failed')", name="status"),
        schema="energy",
    )
    op.create_index("ix_inference_run_home_id", "inference_run", ["home_id"], schema="energy")

    op.create_table(
        "weather_hourly",
        sa.Column("province_code", sa.Text, nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("temp_c", sa.REAL),
        sa.Column("humidity_pct", sa.REAL),
        sa.PrimaryKeyConstraint("province_code", "ts"),
        schema="energy",
    )

    op.execute(
        """
        CREATE TABLE energy.reading (
            ts timestamptz NOT NULL,
            series_id integer NOT NULL,
            value real NOT NULL,
            quality smallint NOT NULL DEFAULT 0,
            PRIMARY KEY (series_id, ts)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE energy.device_estimate (
            ts timestamptz NOT NULL,
            series_id integer NOT NULL,
            value real NOT NULL,
            run_id integer,
            PRIMARY KEY (series_id, ts)
        )
        """
    )
    for table in ("reading", "device_estimate"):
        op.execute(
            f"SELECT create_hypertable('energy.{table}', by_range('ts', INTERVAL '1 day'))"
        )
        op.execute(
            f"ALTER TABLE energy.{table} SET (timescaledb.compress, "
            "timescaledb.compress_segmentby = 'series_id', "
            "timescaledb.compress_orderby = 'ts DESC')"
        )

    op.execute(SET_POLICIES)
    op.execute("SELECT ops.set_policies(true)")


def downgrade() -> None:
    op.execute("SELECT ops.set_policies(false)")
    op.execute("DROP TABLE energy.device_estimate")
    op.execute("DROP TABLE energy.reading")
    op.drop_table("weather_hourly", schema="energy")
    op.drop_table("inference_run", schema="energy")
    op.drop_table("series", schema="energy")
    op.execute("DROP FUNCTION ops.set_policies(boolean)")
