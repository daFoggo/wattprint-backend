"""tb_watch: repeating alerts (once per day, cycle or device run) and device run alerts
(turns on, turns off, runs too long, draws too much); tb_alert kinds for the device ones

Revision ID: b3d9e5f17a2c
Revises: 6a2f8c1e4b97
"""

import sqlalchemy as sa

from alembic import op

revision = "b3d9e5f17a2c"
down_revision = "6a2f8c1e4b97"
branch_labels = None
depends_on = None

OLD_METRICS = (
    "bill_vnd",
    "bill_kwh",
    "forecast_vnd",
    "today_kwh",
    "power_w",
    "device_kwh_today",
    "sql",
)
DEVICE_RUNS = ("device_on", "device_off", "device_run_min", "device_power_w")
OLD_KINDS = (
    "longer_than_usual",
    "standby_high",
    "tier_near",
    "unexplained_load",
    "watch_hit",
    "watch_broken",
)
RUN_KINDS = ("device_on", "device_off", "device_long_run", "device_high_power")


def _check(name: str, table: str, condition: str) -> None:
    op.drop_constraint(op.f(name), table, schema="public")
    op.create_check_constraint(op.f(name), table, condition, schema="public")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def upgrade() -> None:
    # Rows set before this keep firing once; new ones repeat unless asked not to.
    op.add_column(
        "tb_watch",
        sa.Column("repeat", sa.Boolean, nullable=False, server_default=sa.false()),
        schema="public",
    )
    op.alter_column("tb_watch", "repeat", server_default=sa.true(), schema="public")
    _check("ck_tb_watch_metric", "tb_watch", _in("metric", (*OLD_METRICS, *DEVICE_RUNS)))
    _check("ck_tb_watch_device", "tb_watch", "(metric LIKE 'device_%') = (device_id IS NOT NULL)")
    _check("ck_tb_alert_kind", "tb_alert", _in("kind", (*OLD_KINDS, *RUN_KINDS)))


def downgrade() -> None:
    op.execute("DELETE FROM public.tb_alert WHERE " + _in("kind", RUN_KINDS))
    op.execute("DELETE FROM public.tb_watch WHERE " + _in("metric", DEVICE_RUNS))
    _check("ck_tb_alert_kind", "tb_alert", _in("kind", OLD_KINDS))
    _check(
        "ck_tb_watch_device", "tb_watch", "(metric = 'device_kwh_today') = (device_id IS NOT NULL)"
    )
    _check("ck_tb_watch_metric", "tb_watch", _in("metric", OLD_METRICS))
    op.drop_column("tb_watch", "repeat", schema="public")
