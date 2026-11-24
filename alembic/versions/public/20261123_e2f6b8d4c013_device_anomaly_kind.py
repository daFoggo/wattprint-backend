"""tb_alert kind device_anomaly (a device unlike itself in the same context) and the demo
scenario echo_run (wave 2, change 1)

Revision ID: e2f6b8d4c013
Revises: d1e5a7c3b902
"""

from alembic import op

revision = "e2f6b8d4c013"
down_revision = "d1e5a7c3b902"
branch_labels = None
depends_on = None

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
    "usage_anomaly",
)


def _kinds(kinds: tuple[str, ...]) -> None:
    op.drop_constraint(op.f("ck_tb_alert_kind"), "tb_alert", schema="public")
    op.create_check_constraint(
        op.f("ck_tb_alert_kind"),
        "tb_alert",
        "kind IN (" + ", ".join(f"'{k}'" for k in kinds) + ")",
        schema="public",
    )


SCENARIOS = ("heater", "forgotten_load", "base_up", "away", "cold_spell")


def _scenarios(names: tuple[str, ...]) -> None:
    op.drop_constraint(op.f("ck_tb_demo_scenario_name"), "tb_demo_scenario", schema="public")
    op.create_check_constraint(
        op.f("ck_tb_demo_scenario_name"),
        "tb_demo_scenario",
        "name IN (" + ", ".join(f"'{n}'" for n in names) + ")",
        schema="public",
    )


def upgrade() -> None:
    _kinds((*KINDS, "device_anomaly"))
    _scenarios((*SCENARIOS, "echo_run"))  # a device's real run replayed (scripts/scenario.py)


def downgrade() -> None:
    op.execute("DELETE FROM public.tb_demo_scenario WHERE name = 'echo_run'")
    _scenarios(SCENARIOS)
    op.execute("DELETE FROM public.tb_alert WHERE kind = 'device_anomaly'")
    _kinds(KINDS)
