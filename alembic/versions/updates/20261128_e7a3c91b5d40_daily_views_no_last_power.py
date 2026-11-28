"""a daily token sees no day's last sample: today's is the power right now

Revision ID: e7a3c91b5d40
Revises: c4d8a1f6b2e9
"""

from alembic import op

revision = "e7a3c91b5d40"
down_revision = "c4d8a1f6b2e9"
branch_labels = None
depends_on = None

HOME = "copilot_ro.current_home()"
HOURLY = "copilot_ro.current_detail() = 'hourly'"


def _replace(last_w: str) -> None:
    # Same column names and types, so CREATE OR REPLACE keeps the views' grants.
    for family in ("reading", "device_estimate"):
        op.execute(
            f"""
            CREATE OR REPLACE VIEW copilot_ro.{family}_1d WITH (security_barrier = true) AS
            SELECT r.bucket, r.series_id, s.device_id, s.kind, r.avg_w, r.min_w, r.max_w,
                   {last_w}, r.n, r.energy_wh, r.covered_minutes
            FROM public.{family}_1d r
            JOIN public.tb_series s ON s.series_id = r.series_id
            WHERE s.home_id = {HOME}
              AND r.series_id = ANY (ARRAY(SELECT x.series_id FROM public.tb_series x
                                           WHERE x.home_id = {HOME}))"""
        )


def upgrade() -> None:
    _replace(f"CASE WHEN {HOURLY} THEN r.last_w END AS last_w")


def downgrade() -> None:
    _replace("r.last_w")
