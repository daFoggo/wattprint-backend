"""a daily token sees no start hour in an odd-hour alert (its `value` is the hour)

Revision ID: 5a085853fca0
Revises: 5f7ab6bb083c
"""

from alembic import op

revision = "5a085853fca0"
down_revision = "5f7ab6bb083c"
branch_labels = None
depends_on = None

COPILOT = "wattprint_copilot_ro"
HOME = "copilot_ro.current_home()"
HOURLY = "copilot_ro.current_detail() = 'hourly'"


def _alert(daily_payload: str) -> str:
    return f"""
        SELECT a.id, a.home_id, a.device_id, a.kind, a.severity,
               CASE WHEN {HOURLY} THEN a.ts
                    ELSE date_trunc('day', a.ts, 'Asia/Ho_Chi_Minh') END AS ts,
               CASE WHEN {HOURLY} THEN a.payload ELSE {daily_payload} END AS payload,
               a.status
        FROM public.tb_alert a
        WHERE a.home_id = {HOME}
          AND (a.device_id IS NULL
               OR EXISTS (SELECT 1 FROM public.tb_device d
                          WHERE d.id = a.device_id AND d.home_id = a.home_id))"""


OLD = "a.payload - 'start' - 'at'"
NEW = (
    "a.payload - 'start' - 'at' "
    "- (CASE WHEN a.payload->>'signal' = 'odd_hour' THEN 'value' ELSE '' END)"
)


def _replace(payload: str) -> None:
    # Same columns, so CREATE OR REPLACE keeps the view's grants.
    op.execute(
        "CREATE OR REPLACE VIEW copilot_ro.alert WITH (security_barrier = true) AS "
        + _alert(payload)
    )


def upgrade() -> None:
    _replace(NEW)


def downgrade() -> None:
    _replace(OLD)
