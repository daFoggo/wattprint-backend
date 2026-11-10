"""create minute reading and estimate facts over AI dimensions

Revision ID: f39a7b2c5d18
Revises: a4c7e1d93b62
"""

from alembic import op

revision = "f39a7b2c5d18"
down_revision = "a4c7e1d93b62"
branch_labels = None
depends_on = None

FACT_COLUMNS = """
    r.bucket,
    h.home_key,
    d.device_key,
    s.kind AS series_kind,
    s.metric AS metric_code,
    r.avg_w,
    r.min_w,
    r.max_w,
    r.last_w,
    r.n,
    r.energy_wh,
"""


def _create_fact_view(name: str, source: str) -> None:
    op.execute(
        f"""
        CREATE VIEW ai.{name} WITH (security_barrier = true) AS
        SELECT {FACT_COLUMNS}
        FROM public.{source} AS r
        JOIN public.tb_series AS s ON s.series_id = r.series_id
        JOIN ai.dim_home AS h ON h.source_home_id = s.home_id
        LEFT JOIN ai.dim_device AS d ON d.source_device_id = s.device_id
        """
    )
    op.execute(f"REVOKE ALL ON ai.{name} FROM PUBLIC")
    op.execute(f"GRANT SELECT ON ai.{name} TO wattprint_ai")


def upgrade() -> None:
    _create_fact_view("fact_reading_1m", "reading_1m")
    op.execute(
        "COMMENT ON VIEW ai.fact_reading_1m IS "
        "'One-minute reading aggregates keyed by AI home and device dimensions.'"
    )
    _create_fact_view("fact_estimate_1m", "device_estimate_1m")
    op.execute(
        "COMMENT ON VIEW ai.fact_estimate_1m IS "
        "'One-minute device estimate aggregates keyed by AI home and device dimensions.'"
    )


def downgrade() -> None:
    op.execute("REVOKE ALL ON ai.fact_estimate_1m FROM wattprint_ai")
    op.execute("REVOKE ALL ON ai.fact_reading_1m FROM wattprint_ai")
    op.execute("DROP VIEW ai.fact_estimate_1m")
    op.execute("DROP VIEW ai.fact_reading_1m")
