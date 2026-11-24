"""tb_savings_plan: a person's savings plan for a home's billing cycle (web plan page). The insight
worker freezes each day's expected kWh against the model in force at the start, so a weekly refit
cannot learn the saving away.

Revision ID: c7e2f4a9b158
Revises: b5c9e1a7f346
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "c7e2f4a9b158"
down_revision = "b5c9e1a7f346"
branch_labels = None
depends_on = None

APP = "wattprint_app"
NOW = sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "tb_savings_plan",
        sa.Column("id", sa.Uuid, primary_key=True, server_default=sa.text("uuidv7()")),
        sa.Column(
            "user_id",
            sa.Uuid,
            sa.ForeignKey("public.tb_users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "home_id",
            sa.Uuid,
            sa.ForeignKey("public.tb_home.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("start_on", sa.Date, nullable=False),
        sa.Column("end_on", sa.Date, nullable=False),
        sa.Column("model_version", sa.Text, nullable=False),
        sa.Column("sigma", sa.Numeric(12, 4)),
        sa.Column("bias", sa.Numeric(12, 4), nullable=False, server_default="0"),
        sa.Column("forecast_kwh", sa.Numeric(12, 3), nullable=False),
        sa.Column("actions", JSONB, nullable=False),
        sa.Column("days", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("stopped_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('active', 'stopped')", name=op.f("ck_tb_savings_plan_status")
        ),
        sa.CheckConstraint("start_on <= end_on", name=op.f("ck_tb_savings_plan_span")),
        schema="public",
    )
    # One running plan per person and home; the worker scans active plans by home.
    op.execute(
        "CREATE UNIQUE INDEX ux_tb_savings_plan_active "
        "ON public.tb_savings_plan (home_id, user_id) WHERE status = 'active'"
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON public.tb_savings_plan TO {APP}")


def downgrade() -> None:
    op.drop_table("tb_savings_plan", schema="public")
