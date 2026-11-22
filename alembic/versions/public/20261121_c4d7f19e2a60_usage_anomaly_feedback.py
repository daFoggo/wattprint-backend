"""tb_alert kind usage_anomaly (the in-context home anomaly); tb_alert_feedback: a member's verdict
on an alert, which widens that home's band for its kind

Revision ID: c4d7f19e2a60
Revises: a9c3e5f70b18
"""

import sqlalchemy as sa

from alembic import op

revision = "c4d7f19e2a60"
down_revision = "a9c3e5f70b18"
branch_labels = None
depends_on = None

APP = "wattprint_app"
KINDS = (
    "longer_than_usual",
    "standby_high",
    "tier_near",
    "unexplained_load",
    "watch_hit",
    "watch_broken",
    "device_on",
    "device_off",
    "device_long_run",
    "device_high_power",
)


def _kinds(kinds: tuple[str, ...]) -> None:
    op.drop_constraint(op.f("ck_tb_alert_kind"), "tb_alert", schema="public")
    op.create_check_constraint(
        op.f("ck_tb_alert_kind"),
        "tb_alert",
        "kind IN (" + ", ".join(f"'{k}'" for k in kinds) + ")",
        schema="public",
    )


def upgrade() -> None:
    _kinds((*KINDS, "usage_anomaly"))
    op.create_table(
        "tb_alert_feedback",
        sa.Column(
            "alert_id",
            sa.Uuid,
            sa.ForeignKey("public.tb_alert.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            sa.Uuid,
            sa.ForeignKey("public.tb_users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "home_id",
            sa.Uuid,
            sa.ForeignKey("public.tb_home.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("verdict", sa.Text, nullable=False),
        sa.Column(
            "at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.CheckConstraint(
            "verdict IN ('useful', 'not_anomaly')", name=op.f("ck_tb_alert_feedback_verdict")
        ),
        schema="public",
    )
    op.create_index(
        "ix_tb_alert_feedback_home_kind",
        "tb_alert_feedback",
        ["home_id", "kind", "at"],
        schema="public",
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON public.tb_alert_feedback TO {APP}")


def downgrade() -> None:
    op.drop_table("tb_alert_feedback", schema="public")
    op.execute("DELETE FROM public.tb_alert WHERE kind = 'usage_anomaly'")
    _kinds(KINDS)
