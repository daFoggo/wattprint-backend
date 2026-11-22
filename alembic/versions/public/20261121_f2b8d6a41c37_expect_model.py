"""tb_expect_model: a home's learned expected-usage model (LightGBM quantile boosters);
tb_expect_hourly: its expected kWh per hour (quantiles) and the P50's contributions per factor

Revision ID: f2b8d6a41c37
Revises: e7a1c4b92d05
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

from alembic import op

revision = "f2b8d6a41c37"
down_revision = "e7a1c4b92d05"
branch_labels = None
depends_on = None

APP = "wattprint_app"
NOW = sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "tb_expect_model",
        sa.Column("id", sa.Uuid, primary_key=True, server_default=sa.text("uuidv7()")),
        sa.Column(
            "home_id",
            sa.Uuid,
            sa.ForeignKey("public.tb_home.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Text, nullable=False),
        sa.Column("trained_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("features", ARRAY(sa.Text), nullable=False),
        sa.Column("boosters", JSONB, nullable=False),  # {"0.5": LightGBM model string, ...}
        sa.Column("residuals", ARRAY(sa.REAL), nullable=False),
        sa.Column("widen", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("metrics", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.UniqueConstraint("home_id", "version", name=op.f("uq_tb_expect_model_home_version")),
        schema="public",
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_tb_expect_model_active ON public.tb_expect_model (home_id) "
        "WHERE active"
    )
    # shortcut: plain table, not a hypertable; at >1M rows convert it with create_hypertable
    op.create_table(
        "tb_expect_hourly",
        sa.Column(
            "home_id",
            sa.Uuid,
            sa.ForeignKey("public.tb_home.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("ts", sa.DateTime(timezone=True), primary_key=True),
        *(sa.Column(c, sa.REAL, nullable=False) for c in ("p05", "p10", "p50", "p90", "p95")),
        *(
            sa.Column(c, sa.REAL, nullable=False)
            for c in ("c_weather", "c_calendar", "c_occupancy", "c_trend", "c_base")
        ),
        sa.Column("model_version", sa.Text, nullable=False),
        schema="public",
    )
    for table in ("tb_expect_model", "tb_expect_hourly"):
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON public.{table} TO {APP}")


def downgrade() -> None:
    op.drop_table("tb_expect_hourly", schema="public")
    op.drop_table("tb_expect_model", schema="public")
