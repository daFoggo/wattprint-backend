"""tb_home_weather_hourly: hourly weather per home (the recording site's for demo homes);
tb_demo_scenario: simulated loads and events the REFIT replay applies (heater, demo scenarios)

Revision ID: e7a1c4b92d05
Revises: b3d9e5f17a2c
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "e7a1c4b92d05"
down_revision = "b3d9e5f17a2c"
branch_labels = None
depends_on = None

APP = "wattprint_app"
SCENARIOS = ("heater", "forgotten_load", "base_up", "away", "cold_spell")


def upgrade() -> None:
    op.create_table(
        "tb_home_weather_hourly",
        sa.Column(
            "home_id",
            sa.Uuid,
            sa.ForeignKey("public.tb_home.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("ts", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("temp_c", sa.REAL),
        sa.Column("humidity_pct", sa.REAL),
        sa.Column("apparent_c", sa.REAL),
        sa.Column("cloud_pct", sa.REAL),
        sa.Column("radiation_wm2", sa.REAL),
        sa.Column("precip_mm", sa.REAL),
        sa.Column("is_day", sa.Boolean),
        sa.Column("wind_ms", sa.REAL),
        schema="public",
    )
    op.create_table(
        "tb_demo_scenario",
        sa.Column("id", sa.Uuid, primary_key=True, server_default=sa.text("uuidv7()")),
        sa.Column(
            "home_id",
            sa.Uuid,
            sa.ForeignKey("public.tb_home.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True)),
        sa.Column("params", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        # false: a demo event, kept out of training and backtests; true: part of the home (heater)
        sa.Column("train", sa.Boolean, nullable=False),
        sa.CheckConstraint(
            "name IN (" + ", ".join(f"'{n}'" for n in SCENARIOS) + ")",
            name=op.f("ck_tb_demo_scenario_name"),
        ),
        sa.CheckConstraint(
            "ends_at IS NULL OR ends_at > starts_at", name=op.f("ck_tb_demo_scenario_window")
        ),
        schema="public",
    )
    op.create_index(
        "ix_tb_demo_scenario_home", "tb_demo_scenario", ["home_id", "starts_at"], schema="public"
    )
    for table in ("tb_home_weather_hourly", "tb_demo_scenario"):
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON public.{table} TO {APP}")


def downgrade() -> None:
    op.drop_table("tb_demo_scenario", schema="public")
    op.drop_table("tb_home_weather_hourly", schema="public")
