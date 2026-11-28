"""an hourly token sees an alert to the hour: `ts` cut to the hour, no `at` minute

Revision ID: b7d3e1a9c625
Revises: a4f9c2e7b318
"""

from alembic import op

revision = "b7d3e1a9c625"
down_revision = "a4f9c2e7b318"
branch_labels = None
depends_on = None

HOME = "copilot_ro.current_home()"
HOURLY = "copilot_ro.current_detail() = 'hourly'"
DAILY_PAYLOAD = (
    "a.payload - 'start' - 'at' "
    "- (CASE WHEN a.payload->>'signal' = 'odd_hour' THEN 'value' ELSE '' END)"
)


def _replace(hourly_ts: str, hourly_payload: str) -> None:
    # Same columns, so CREATE OR REPLACE keeps the view's grants.
    op.execute(
        f"""CREATE OR REPLACE VIEW copilot_ro.alert WITH (security_barrier = true) AS
        SELECT a.id, a.home_id, a.device_id, a.kind, a.severity,
               CASE WHEN {HOURLY} THEN {hourly_ts}
                    ELSE date_trunc('day', a.ts, 'Asia/Ho_Chi_Minh') END AS ts,
               CASE WHEN {HOURLY} THEN {hourly_payload} ELSE {DAILY_PAYLOAD} END AS payload,
               a.status
        FROM public.tb_alert a
        WHERE a.home_id = {HOME}
          AND (a.device_id IS NULL
               OR EXISTS (SELECT 1 FROM public.tb_device d
                          WHERE d.id = a.device_id AND d.home_id = a.home_id))"""
    )


def upgrade() -> None:
    _replace("date_trunc('hour', a.ts, 'Asia/Ho_Chi_Minh')", "a.payload - 'at'")


def downgrade() -> None:
    _replace("a.ts", "a.payload")
