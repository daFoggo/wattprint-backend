"""initial energy module: series, readings, estimates and weather

Revision ID: b9d2e6f0a384
Revises: 7a91e4d2b6c8
"""

import sqlalchemy as sa

from alembic import op

revision = "b9d2e6f0a384"
down_revision = "7a91e4d2b6c8"
branch_labels = None
depends_on = None

UUID7 = sa.text("uuidv7()")

# Task 4 extends this body with CREATE OR REPLACE FUNCTION.
SET_POLICIES = """
CREATE FUNCTION public.set_policies(enabled boolean) RETURNS void
LANGUAGE plpgsql
SET search_path = public, pg_catalog AS $$
BEGIN
    IF enabled THEN
        PERFORM add_compression_policy('public.tb_reading', INTERVAL '2 days',
                                       if_not_exists => true);
        PERFORM add_compression_policy('public.tb_device_estimate', INTERVAL '2 days',
                                       if_not_exists => true);
        PERFORM add_retention_policy('public.tb_reading', INTERVAL '400 days',
                                     if_not_exists => true);
        PERFORM add_retention_policy('public.tb_device_estimate', INTERVAL '400 days',
                                     if_not_exists => true);
    ELSE
        PERFORM remove_compression_policy('public.tb_reading', if_exists => true);
        PERFORM remove_compression_policy('public.tb_device_estimate', if_exists => true);
        PERFORM remove_retention_policy('public.tb_reading', if_exists => true);
        PERFORM remove_retention_policy('public.tb_device_estimate', if_exists => true);
    END IF;
END
$$
"""


def upgrade() -> None:
    op.create_table(
        "tb_series",
        sa.Column("series_id", sa.Uuid, server_default=UUID7, primary_key=True),
        sa.Column("home_id", sa.Uuid, nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("device_id", sa.Uuid),
        sa.Column("meter_id", sa.Uuid),
        sa.Column("source_channel", sa.Text),
        sa.Column("metric", sa.String(64), nullable=False),
        sa.Column("unit", sa.Text, nullable=False),
        sa.ForeignKeyConstraint(["home_id"], ["public.tb_home.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["device_id"], ["public.tb_device.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["meter_id"], ["public.tb_meter.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["metric"], ["public.cat_metric.event_type"]),
        sa.CheckConstraint("kind IN ('main','plug','device')", name="kind"),
        sa.CheckConstraint("kind <> 'main' OR device_id IS NULL", name="main_has_no_device"),
        sa.CheckConstraint(
            "kind NOT IN ('plug','device') OR device_id IS NOT NULL",
            name="device_kinds_need_device",
        ),
        sa.UniqueConstraint(
            "home_id",
            "kind",
            "device_id",
            "metric",
            name="uq_series_home_kind_device_metric",
            postgresql_nulls_not_distinct=True,
        ),
        schema="public",
    )

    op.create_table(
        "tb_inference_run",
        sa.Column("run_id", sa.Uuid, server_default=UUID7, primary_key=True),
        sa.Column("home_id", sa.Uuid, nullable=False),
        sa.Column("model_name", sa.Text, nullable=False),
        sa.Column("model_version", sa.Text, nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.Text, nullable=False, server_default="running"),
        sa.ForeignKeyConstraint(["home_id"], ["public.tb_home.id"], ondelete="CASCADE"),
        sa.CheckConstraint("status IN ('running','ok','failed')", name="status"),
        schema="public",
    )

    op.create_table(
        "tb_weather_hourly",
        sa.Column("province_code", sa.Text, nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("temp_c", sa.REAL),
        sa.Column("humidity_pct", sa.REAL),
        sa.PrimaryKeyConstraint("province_code", "ts"),
        schema="public",
    )

    op.execute(
        """
        CREATE TABLE public.tb_reading (
            ts timestamptz NOT NULL,
            series_id uuid NOT NULL,
            value real NOT NULL,
            quality smallint NOT NULL DEFAULT 0,
            CONSTRAINT pk_reading PRIMARY KEY (series_id, ts)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE public.tb_device_estimate (
            ts timestamptz NOT NULL,
            series_id uuid NOT NULL,
            value real NOT NULL,
            run_id uuid,
            CONSTRAINT pk_device_estimate PRIMARY KEY (series_id, ts)
        )
        """
    )
    for table in ("tb_reading", "tb_device_estimate"):
        op.execute(f"SELECT create_hypertable('public.{table}', by_range('ts', INTERVAL '1 day'))")
        op.execute(
            f"ALTER TABLE public.{table} SET (timescaledb.compress, "
            "timescaledb.compress_segmentby = 'series_id', "
            "timescaledb.compress_orderby = 'ts DESC')"
        )

    op.execute(SET_POLICIES)
    op.execute("SELECT public.set_policies(true)")


def downgrade() -> None:
    op.execute("SELECT public.set_policies(false)")
    op.execute("DROP TABLE public.tb_device_estimate")
    op.execute("DROP TABLE public.tb_reading")
    op.drop_table("tb_weather_hourly", schema="public")
    op.drop_table("tb_inference_run", schema="public")
    op.drop_table("tb_series", schema="public")
    op.execute("DROP FUNCTION public.set_policies(boolean)")
