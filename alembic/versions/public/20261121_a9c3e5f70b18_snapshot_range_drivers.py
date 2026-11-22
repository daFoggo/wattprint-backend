"""tb_forecast_snapshot: the forecast's P10/P90 kWh and what explains tomorrow's change

Revision ID: a9c3e5f70b18
Revises: f2b8d6a41c37
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "a9c3e5f70b18"
down_revision = "f2b8d6a41c37"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tb_forecast_snapshot", sa.Column("kwh_p10", sa.Numeric(12, 3)), schema="public")
    op.add_column("tb_forecast_snapshot", sa.Column("kwh_p90", sa.Numeric(12, 3)), schema="public")
    # {"version", "kwh_now", "p50_daily": {day: kWh}, "groups_daily": {day: {group: kWh}}}
    op.add_column("tb_forecast_snapshot", sa.Column("drivers", JSONB), schema="public")


def downgrade() -> None:
    for c in ("drivers", "kwh_p90", "kwh_p10"):
        op.drop_column("tb_forecast_snapshot", c, schema="public")
