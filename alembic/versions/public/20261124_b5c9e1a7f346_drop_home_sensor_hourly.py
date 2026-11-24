"""Drop the indoor sensors (tb_home_sensor_hourly, tb_expect_hourly.c_indoor): the product uses the
recording site's weather only (Product Owner, 2026-11-24). The REFIT Smart Home files stay in
dataset/refit_smart_home; downgrade restores the empty table and column.

Revision ID: b5c9e1a7f346
Revises: a4b8d0f6e235
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "b5c9e1a7f346"
down_revision = "a4b8d0f6e235"
branch_labels = None
depends_on = None

APP = "wattprint_app"
REALS = (
    "indoor_temp_c",
    "indoor_rh_pct",
    "gas_m3",
    "station_temp_c",
    "station_rh_pct",
    "station_wind_ms",
    "station_radiation_wm2",
    "station_precip_mm",
)


def upgrade() -> None:
    op.drop_column("tb_expect_hourly", "c_indoor", schema="public")
    op.drop_table("tb_home_sensor_hourly", schema="public")


def downgrade() -> None:
    op.create_table(
        "tb_home_sensor_hourly",
        sa.Column(
            "home_id",
            sa.Uuid,
            sa.ForeignKey("public.tb_home.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("ts", sa.DateTime(timezone=True), primary_key=True),
        *(sa.Column(c, sa.REAL) for c in REALS),
        sa.Column("occupied_rooms", sa.SmallInteger),
        sa.Column("sensing_rooms", sa.SmallInteger),
        sa.Column("rooms", JSONB),
        schema="public",
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON public.tb_home_sensor_hourly TO {APP}")
    op.add_column(
        "tb_expect_hourly",
        sa.Column("c_indoor", sa.REAL, nullable=False, server_default="0"),
        schema="public",
    )
