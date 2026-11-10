"""copilot_ro read-only views, scope tokens and per-object role grants

Revision ID: 4d7b1e9a3c52
Revises: 9e2c4a6b8d10
"""

import sqlalchemy as sa

from alembic import op

revision = "4d7b1e9a3c52"
down_revision = "e3a7c9b1d5f2"
branch_labels = None
depends_on = None

APP = "wattprint_app"
INGEST = "wattprint_ingest"
COPILOT = "wattprint_copilot_ro"

# The Copilot session names its home with an opaque token (setting app.copilot_token) that
# copilot_ro.current_home() resolves; a missing, expired, unknown or malformed token yields
# NULL, and `col = NULL` matches no row: zero rows, never an error.
HOME = "copilot_ro.current_home()"

TOKEN_REGEX = "^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
CURRENT_HOME_FN = f"""
CREATE FUNCTION copilot_ro.current_home() RETURNS integer
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp AS $$
    SELECT t.home_id
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

# view name -> SELECT body. Every view is owned by the migration owner, so the Copilot role
# needs privileges on the views only. Rows are always reached through the owning
# device/series/home; a denormalised home_id is never trusted on its own.
VIEWS: dict[str, str] = {
    "home": f"""
        SELECT h.id, h.name, h.postal_code, h.province_code, h.home_type, h.floor_area_m2,
               h.year_built, h.occupants, h.timezone, h.tariff_plan_code, h.billing_cycle_day
        FROM public.tb_home h
        WHERE h.id = {HOME}""",
    "device": f"""
        SELECT d.id, d.device_type_code, d.name, d.room, d.origin, d.show_on_timeline,
               d.active_from, d.active_to, d.merged_into_id, d.deleted_at
        FROM public.tb_device d
        WHERE d.home_id = {HOME}""",
    "series": f"""
        SELECT s.series_id, s.kind, s.device_id, s.metric, s.unit
        FROM public.tb_series s
        WHERE s.home_id = {HOME}""",
    "bill": f"""
        SELECT b.id, b.home_id, b.period_start, b.period_end, b.version_id, b.kwh_total,
               b.amount_before_vat, b.vat_amount, b.amount_total, b.coverage,
               b.tariff_straddle, b.status, b.computed_at
        FROM public.tb_bill b
        WHERE b.home_id = {HOME}""",
    "bill_item": f"""
        SELECT i.id, i.bill_id, i.device_id, i.label, i.kwh, i.share, i.amount
        FROM public.tb_bill_item i
        JOIN public.tb_bill b ON b.id = i.bill_id
        WHERE b.home_id = {HOME}""",
    "alert": f"""
        SELECT a.id, a.home_id, a.device_id, a.kind, a.severity, a.ts, a.payload, a.status
        FROM public.tb_alert a
        WHERE a.home_id = {HOME}
          AND (a.device_id IS NULL
               OR EXISTS (SELECT 1 FROM public.tb_device d
                          WHERE d.id = a.device_id AND d.home_id = a.home_id))""",
    "device_cycle": f"""
        SELECT c.home_id, c.device_id, c.start_ts, c.end_ts, c.energy_wh, c.peak_w
        FROM public.tb_device_cycle c
        JOIN public.tb_device d ON d.id = c.device_id
        WHERE d.home_id = {HOME} AND c.home_id = d.home_id""",
    "suggestion": f"""
        SELECT g.id, g.home_id, g.device_id, g.alert_id, g.kind, g.title, g.body,
               g.expected_kwh, g.expected_amount, g.status, g.created_at
        FROM public.tb_suggestion g
        WHERE g.home_id = {HOME}
          AND (g.device_id IS NULL
               OR EXISTS (SELECT 1 FROM public.tb_device d
                          WHERE d.id = g.device_id AND d.home_id = g.home_id))""",
    "forecast_snapshot": f"""
        SELECT f.id, f.home_id, f.generated_at, f.horizon_date, f.kwh, f.amount,
               f.tier_cross_date, f.model_version
        FROM public.tb_forecast_snapshot f
        WHERE f.home_id = {HOME}""",
}
for _family in ("reading", "device_estimate"):
    for _res, _cols in (("1m", AGG_COLS_1M), ("1h", AGG_COLS_COVERED), ("1d", AGG_COLS_COVERED)):
        # The join to public.tb_series is what guarantees ownership. The ANY(ARRAY(...)) predicate
        # is redundant for correctness but is an InitPlan, so the planner pushes it into the
        # aggregate as an index condition on series_id; with the join alone, a continuous
        # aggregate is computed for every home and filtered afterwards.
        VIEWS[f"{_family}_{_res}"] = f"""
        SELECT {_cols}
        FROM public.{_family}_{_res} r
        JOIN public.tb_series s ON s.series_id = r.series_id
        WHERE s.home_id = {HOME}
          AND r.series_id = ANY (ARRAY(SELECT x.series_id FROM public.tb_series x
                                       WHERE x.home_id = {HOME}))"""

DOMAIN_TABLES = {
    "core": (
        "tb_home",
        "tb_home_member",
        "tb_home_invite",
        "tb_meter",
        "tb_device",
        "tb_device_alert_rule",
    ),
    "billing": ("tb_tariff_plan", "tb_tariff_version", "tb_tariff_tier", "tb_bill", "tb_bill_item"),
    "insight": ("tb_device_cycle", "tb_alert", "tb_forecast_snapshot", "tb_cohort_stat"),
    "copilot": (
        "tb_suggestion",
        "tb_suggestion_feedback",
        "tb_savings_measure",
        "tb_scope_token",
    ),
    "knowledge": ("tb_document", "tb_chunk"),
}
AGGREGATES = tuple(
    f"public.{family}_{res}"
    for family in ("reading", "device_estimate")
    for res in ("1m", "1h", "1d")
)
OPS_OBJECTS = ("tb_ingest_batch", "tb_ingest_checkpoint", "series_daily_coverage", "stale_series")
SEQUENCES = (
    ("public", "tb_series", "series_id"),
    ("public", "tb_inference_run", "run_id"),
    ("public", "tb_chunk", "id"),
)
SCHEMAS_ALL = ("public",)

# (privileges, role, objects). Table-level only; schema USAGE and sequences are listed below.
DML = "SELECT, INSERT, UPDATE, DELETE"
TABLE_GRANTS: list[tuple[str, str, tuple[str, ...]]] = [
    (
        "SELECT",
        COPILOT,
        tuple(f"copilot_ro.{v}" for v in VIEWS)
        + (
            "public.tb_document",
            "public.tb_chunk",
            "public.cat_metric",
            "public.cat_device_type",
            "public.tb_tariff_plan",
            "public.tb_tariff_version",
            "public.tb_tariff_tier",
        ),
    ),
    ("SELECT", INGEST, ("public.tb_meter", "public.tb_series")),
    ("SELECT, INSERT", INGEST, ("public.tb_reading",)),
    (
        "SELECT, INSERT, UPDATE",
        INGEST,
        ("public.tb_device_estimate", "public.tb_ingest_batch", "public.tb_ingest_checkpoint"),
    ),
    (
        DML,
        APP,
        tuple(f"public.{t}" for ts in DOMAIN_TABLES.values() for t in ts if t != "tb_scope_token")
        + (
            "public.tb_series",
            "public.tb_inference_run",
            "public.tb_weather_hourly",
            "public.tb_users",
            "public.tb_refresh_tokens",
        ),
    ),
    ("SELECT, INSERT, DELETE", APP, ("public.tb_scope_token",)),
    (
        "SELECT",
        APP,
        ("public.cat_metric", "public.cat_device_type")
        + AGGREGATES
        + tuple(f"public.{o}" for o in OPS_OBJECTS),
    ),
]
SCHEMA_USAGE: list[tuple[str, tuple[str, ...]]] = [
    (COPILOT, ("copilot_ro", "public")),
    (INGEST, ("public",)),
    (APP, SCHEMAS_ALL),
]


def _grant_sequences(role: str) -> None:
    for schema, table, col in SEQUENCES:
        op.execute(
            "DO $$ BEGIN EXECUTE format('GRANT USAGE ON SEQUENCE %s TO " + role + "', "
            f"pg_get_serial_sequence('{schema}.{table}', '{col}')); END $$"
        )


def _revoke_sequences(role: str) -> None:
    for schema, table, col in SEQUENCES:
        op.execute(
            "DO $$ BEGIN EXECUTE format('REVOKE ALL ON SEQUENCE %s FROM " + role + "', "
            f"pg_get_serial_sequence('{schema}.{table}', '{col}')); END $$"
        )


def _scope_token() -> None:
    op.create_table(
        "tb_scope_token",
        sa.Column("token", sa.UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("home_id", sa.Integer, nullable=False),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now() + interval '5 minutes'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["home_id"], ["public.tb_home.id"], ondelete="CASCADE"),
        schema="public",
    )


def upgrade() -> None:
    _scope_token()
    op.execute("CREATE SCHEMA copilot_ro")
    op.execute("REVOKE ALL ON SCHEMA copilot_ro FROM PUBLIC")
    op.execute(CURRENT_HOME_FN)
    op.execute("REVOKE ALL ON FUNCTION copilot_ro.current_home() FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION copilot_ro.current_home() TO {COPILOT}")
    for name, body in VIEWS.items():
        op.execute(f"CREATE VIEW copilot_ro.{name} WITH (security_barrier = true) AS {body}")
        op.execute(f"REVOKE ALL ON copilot_ro.{name} FROM PUBLIC")
    for role, schemas in SCHEMA_USAGE:
        for schema in schemas:
            op.execute(f"GRANT USAGE ON SCHEMA {schema} TO {role}")
    for privs, role, objects in TABLE_GRANTS:
        for obj in objects:
            op.execute(f"GRANT {privs} ON {obj} TO {role}")
    _grant_sequences(APP)


def downgrade() -> None:
    # Roles and their attributes are never touched; only this revision's grants are revoked.
    _revoke_sequences(APP)
    for _privs, role, objects in reversed(TABLE_GRANTS):
        if role == COPILOT:
            continue  # the copilot_ro views are dropped below; the rest is revoked here
        for obj in objects:
            op.execute(f"REVOKE ALL ON {obj} FROM {role}")
    for obj in TABLE_GRANTS[0][2]:
        if not obj.startswith("copilot_ro."):
            op.execute(f"REVOKE ALL ON {obj} FROM {COPILOT}")
    for role, schemas in SCHEMA_USAGE:
        for schema in schemas:
            op.execute(f"REVOKE USAGE ON SCHEMA {schema} FROM {role}")
    for name in reversed(list(VIEWS)):
        op.execute(f"DROP VIEW copilot_ro.{name}")
    op.execute(f"REVOKE ALL ON FUNCTION copilot_ro.current_home() FROM {COPILOT}")
    op.execute("DROP FUNCTION copilot_ro.current_home()")
    op.execute("DROP SCHEMA copilot_ro")
    op.drop_table("tb_scope_token", schema="public")
