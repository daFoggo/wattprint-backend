"""tb_watch: thresholds a user asked Wappi to watch ("tell me when this month's bill passes
1 million"), checked by the insight worker; tb_alert kinds watch_hit and watch_broken

Revision ID: 6a2f8c1e4b97
Revises: 4d1e7b9c2a58
"""

import sqlalchemy as sa

from alembic import op

revision = "6a2f8c1e4b97"
down_revision = "4d1e7b9c2a58"
branch_labels = None
depends_on = None

APP = "wattprint_app"
NOW = sa.text("now()")
METRICS = (
    "bill_vnd",
    "bill_kwh",
    "forecast_vnd",
    "today_kwh",
    "power_w",
    "device_kwh_today",
    "sql",
)
OLD_KINDS = ("longer_than_usual", "standby_high", "tier_near", "unexplained_load")
NEW_KINDS = (*OLD_KINDS, "watch_hit", "watch_broken")


def _kinds(kinds: tuple[str, ...]) -> None:
    op.drop_constraint(op.f("ck_tb_alert_kind"), "tb_alert", schema="public")
    op.create_check_constraint(
        op.f("ck_tb_alert_kind"),
        "tb_alert",
        "kind IN (" + ", ".join(f"'{k}'" for k in kinds) + ")",
        schema="public",
    )


def upgrade() -> None:
    op.create_table(
        "tb_watch",
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
        sa.Column("device_id", sa.Uuid, sa.ForeignKey("public.tb_device.id", ondelete="CASCADE")),
        sa.Column("metric", sa.Text, nullable=False),
        sa.Column("label", sa.Text, nullable=False),
        sa.Column("sql_text", sa.Text),
        sa.Column("op", sa.String(2), nullable=False),
        sa.Column("threshold", sa.Numeric(14, 3), nullable=False),
        sa.Column("unit", sa.Text, nullable=False, server_default=""),
        sa.Column("every_s", sa.Integer, nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("next_check_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("last_value", sa.Numeric(14, 3)),
        sa.Column("last_checked_at", sa.DateTime(timezone=True)),
        sa.Column("fails", sa.SmallInteger, nullable=False, server_default="0"),
        sa.Column("fired_at", sa.DateTime(timezone=True)),
        sa.Column("utterance", sa.Text, nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.CheckConstraint(
            "metric IN (" + ", ".join(f"'{m}'" for m in METRICS) + ")",
            name=op.f("ck_tb_watch_metric"),
        ),
        sa.CheckConstraint("op IN ('gt', 'lt')", name=op.f("ck_tb_watch_op")),
        sa.CheckConstraint(
            "status IN ('active', 'fired', 'expired', 'cancelled', 'broken')",
            name=op.f("ck_tb_watch_status"),
        ),
        sa.CheckConstraint("every_s >= 60", name=op.f("ck_tb_watch_every")),
        sa.CheckConstraint(
            "(metric = 'sql') = (sql_text IS NOT NULL)", name=op.f("ck_tb_watch_sql")
        ),
        sa.CheckConstraint(
            "(metric = 'device_kwh_today') = (device_id IS NOT NULL)",
            name=op.f("ck_tb_watch_device"),
        ),
        schema="public",
    )
    # The worker's scan: only active watches, soonest first.
    op.execute(
        "CREATE INDEX ix_tb_watch_due ON public.tb_watch (next_check_at) WHERE status = 'active'"
    )
    op.create_index("ix_tb_watch_home_user", "tb_watch", ["home_id", "user_id"], schema="public")
    op.create_index("ix_public_tb_watch_device_id", "tb_watch", ["device_id"], schema="public")
    # Stored SQL lives here: the copilot role gets nothing on it.
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON public.tb_watch TO {APP}")
    _kinds(NEW_KINDS)


def downgrade() -> None:
    op.execute("DELETE FROM public.tb_alert WHERE kind IN ('watch_hit', 'watch_broken')")
    _kinds(OLD_KINDS)
    op.drop_table("tb_watch", schema="public")
