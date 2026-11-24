"""tb_home_sensor_hourly: a home's indoor sensors per hour (Pro: room temperature and humidity,
occupied rooms, gas, the on-site weather station); tb_expect_hourly.c_indoor, their contribution

Revision ID: f3a7c9e5d124
Revises: e2f6b8d4c013
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "f3a7c9e5d124"
down_revision = "e2f6b8d4c013"
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


def downgrade() -> None:
    op.drop_column("tb_expect_hourly", "c_indoor", schema="public")
    op.drop_table("tb_home_sensor_hourly", schema="public")
