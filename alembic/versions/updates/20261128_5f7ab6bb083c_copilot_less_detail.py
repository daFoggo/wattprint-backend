"""copilot reads less: no minute or run views, no home identity, hours only for an 'hourly' token

Revision ID: 5f7ab6bb083c
Revises: 7ed04a4f7308
"""

import sqlalchemy as sa

from alembic import op

revision = "5f7ab6bb083c"
down_revision = "7ed04a4f7308"
branch_labels = None
depends_on = None

COPILOT = "wattprint_copilot_ro"
HOME = "copilot_ro.current_home()"
HOURLY = "copilot_ro.current_detail() = 'hourly'"
AND_HOURLY = f"\n          AND {HOURLY}"
LEVELS = "('daily', 'hourly')"

TOKEN_REGEX = "^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
# Same lookup as current_home(): a missing, expired, unknown or malformed token yields NULL.
CURRENT_DETAIL_FN = f"""
CREATE FUNCTION copilot_ro.current_detail() RETURNS text
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp AS $$
    SELECT t.detail
    FROM public.tb_scope_token t
    WHERE t.expires_at > now()
      AND t.token = (
          SELECT v::uuid FROM (SELECT current_setting('app.copilot_token', true) AS v) x
          WHERE v ~ '{TOKEN_REGEX}'
      )
$$
"""

AGG_COLS = "r.bucket, r.series_id, s.device_id, s.kind, r.avg_w, r.min_w, r.max_w, r.last_w, r.n"
AGG_COLS_COVERED = AGG_COLS + ", r.energy_wh, r.covered_minutes"
AGG_COLS_1M = AGG_COLS + ", r.energy_wh"


def _agg(family: str, res: str, cols: str, extra: str = "") -> str:
    # Same shape as 4d7b1e9a3c52: the ANY(ARRAY(...)) InitPlan keeps the series index condition.
    return f"""
        SELECT {cols}
        FROM public.{family}_{res} r
        JOIN public.tb_series s ON s.series_id = r.series_id
        WHERE s.home_id = {HOME}
          AND r.series_id = ANY (ARRAY(SELECT x.series_id FROM public.tb_series x
                                       WHERE x.home_id = {HOME})){extra}"""


ALERT_WHERE = f"""
        FROM public.tb_alert a
        WHERE a.home_id = {HOME}
          AND (a.device_id IS NULL
               OR EXISTS (SELECT 1 FROM public.tb_device d
                          WHERE d.id = a.device_id AND d.home_id = a.home_id))"""

NEW = {
    "home": f"""
        SELECT h.id, h.province_code, h.home_type, h.floor_area_m2, h.year_built, h.timezone,
               h.tariff_plan_code, h.billing_cycle_day
        FROM public.tb_home h
        WHERE h.id = {HOME}""",
    "alert": f"""
        SELECT a.id, a.home_id, a.device_id, a.kind, a.severity,
               CASE WHEN {HOURLY} THEN a.ts
                    ELSE date_trunc('day', a.ts, 'Asia/Ho_Chi_Minh') END AS ts,
               CASE WHEN {HOURLY} THEN a.payload ELSE a.payload - 'start' - 'at' END AS payload,
               a.status{ALERT_WHERE}""",
    "reading_1h": _agg("reading", "1h", AGG_COLS_COVERED, AND_HOURLY),
    "device_estimate_1h": _agg("device_estimate", "1h", AGG_COLS_COVERED, AND_HOURLY),
}
OLD = {
    "home": f"""
        SELECT h.id, h.name, h.postal_code, h.province_code, h.home_type, h.floor_area_m2,
               h.year_built, h.occupants, h.timezone, h.tariff_plan_code, h.billing_cycle_day
        FROM public.tb_home h
        WHERE h.id = {HOME}""",
    "alert": f"""
        SELECT a.id, a.home_id, a.device_id, a.kind, a.severity, a.ts, a.payload, a.status
        {ALERT_WHERE}""",
    "reading_1h": _agg("reading", "1h", AGG_COLS_COVERED),
    "device_estimate_1h": _agg("device_estimate", "1h", AGG_COLS_COVERED),
}
GONE = {
    "reading_1m": _agg("reading", "1m", AGG_COLS_1M),
    "device_estimate_1m": _agg("device_estimate", "1m", AGG_COLS_1M),
    "device_cycle": f"""
        SELECT c.home_id, c.device_id, c.start_ts, c.end_ts, c.energy_wh, c.peak_w
        FROM public.tb_device_cycle c
        JOIN public.tb_device d ON d.id = c.device_id
        WHERE d.home_id = {HOME} AND c.home_id = d.home_id""",
}


def _create(views: dict[str, str]) -> None:
    for name, body in views.items():
        op.execute(f"CREATE VIEW copilot_ro.{name} WITH (security_barrier = true) AS {body}")
        op.execute(f"REVOKE ALL ON copilot_ro.{name} FROM PUBLIC")
        op.execute(f"GRANT SELECT ON copilot_ro.{name} TO {COPILOT}")


def _drop(views: dict[str, str]) -> None:
    for name in views:
        op.execute(f"DROP VIEW copilot_ro.{name}")


def upgrade() -> None:
    op.add_column("tb_home", sa.Column("ai_detail", sa.String(8)), schema="public")
    op.create_check_constraint(
        "ai_detail", "tb_home", f"ai_detail IN {LEVELS}", schema="public"
    )
    op.add_column(
        "tb_scope_token",
        sa.Column("detail", sa.String(8), nullable=False, server_default="daily"),
        schema="public",
    )
    op.create_check_constraint(
        "detail", "tb_scope_token", f"detail IN {LEVELS}", schema="public"
    )
    op.execute(CURRENT_DETAIL_FN)
    op.execute("REVOKE ALL ON FUNCTION copilot_ro.current_detail() FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION copilot_ro.current_detail() TO {COPILOT}")
    _drop(GONE)
    _drop(OLD)
    _create(NEW)


def downgrade() -> None:
    _drop(NEW)
    _create(OLD)
    _create(GONE)
    op.execute("DROP FUNCTION copilot_ro.current_detail()")
    # Each check constraint goes with its column.
    op.drop_column("tb_scope_token", "detail", schema="public")
    op.drop_column("tb_home", "ai_detail", schema="public")
