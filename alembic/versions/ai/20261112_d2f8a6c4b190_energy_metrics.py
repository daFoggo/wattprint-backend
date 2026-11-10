"""register AI energy metrics with fact-scoped SQL queries

Revision ID: d2f8a6c4b190
Revises: c6a9e2f1b743
"""

import sqlalchemy as sa

from alembic import op

revision = "d2f8a6c4b190"
down_revision = "c6a9e2f1b743"
branch_labels = None
depends_on = None

METRICS = [
    (
        "energy_by_channel_day",
        'Điện năng theo channel và ngày',
        "kWh",
        "sum",
        """SELECT home_key, device_key, date_trunc('day', bucket) AS day,
                  sum(energy_wh) / 1000.0 AS energy_kwh
           FROM ai.fact_energy
           WHERE home_key = :home_key AND bucket >= :from_ts AND bucket < :to_ts
           GROUP BY home_key, device_key, date_trunc('day', bucket)""",
    ),
    (
        "cumulative_energy_by_channel",
        'Điện năng lũy kế theo channel trong kỳ hóa đơn',
        "kWh",
        "last",
        """SELECT DISTINCT ON (device_key) home_key, device_key,
                  billing_cycle_start, bucket, cumulative_energy_wh / 1000.0 AS energy_kwh
           FROM ai.fact_energy
           WHERE home_key = :home_key AND bucket >= :from_ts AND bucket < :to_ts
           ORDER BY device_key, bucket DESC""",
    ),
    (
        "allocated_cost_by_channel_day",
        'Chi phí phân bổ theo channel và ngày',
        "VND",
        "sum",
        """SELECT home_key, device_key, date_trunc('day', bucket) AS day,
                  CASE WHEN bool_and(allocated_cost IS NOT NULL)
                       THEN sum(allocated_cost) END AS allocated_cost_vnd,
                  count(*) FILTER (WHERE allocated_cost IS NULL) AS unpriced_minutes
           FROM ai.fact_energy
           WHERE home_key = :home_key AND bucket >= :from_ts AND bucket < :to_ts
           GROUP BY home_key, device_key, date_trunc('day', bucket)""",
    ),
    (
        "top_channels_by_energy",
        'Channel có điện năng cao nhất',
        "kWh",
        "sum",
        """SELECT device_key, sum(energy_wh) / 1000.0 AS energy_kwh
           FROM ai.fact_energy
           WHERE home_key = :home_key AND bucket >= :from_ts AND bucket < :to_ts
           GROUP BY device_key ORDER BY energy_kwh DESC LIMIT :limit""",
    ),
    (
        "top_channels_by_allocated_cost",
        'Channel có chi phí phân bổ cao nhất',
        "VND",
        "sum",
        """SELECT device_key,
                  CASE WHEN bool_and(allocated_cost IS NOT NULL)
                       THEN sum(allocated_cost) END AS allocated_cost_vnd,
                  count(*) FILTER (WHERE allocated_cost IS NULL) AS unpriced_minutes
           FROM ai.fact_energy
           WHERE home_key = :home_key AND bucket >= :from_ts AND bucket < :to_ts
           GROUP BY device_key
           ORDER BY allocated_cost_vnd DESC NULLS LAST LIMIT :limit""",
    ),
]


def upgrade() -> None:
    op.create_table(
        "metric_definition",
        sa.Column("metric_code", sa.String(96), nullable=False),
        sa.Column("fact_name", sa.String(96), nullable=False, server_default="fact_energy"),
        sa.Column("label_vi", sa.String(255), nullable=False),
        sa.Column("unit", sa.String(32), nullable=False),
        sa.Column("aggregation", sa.String(16), nullable=False),
        sa.Column("sql_query", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.PrimaryKeyConstraint("metric_code", name="pk_metric_definition"),
        sa.CheckConstraint(
            "fact_name = 'fact_energy'",
            name="ck_metric_definition_fact_name",
        ),
        sa.CheckConstraint(
            "aggregation IN ('sum','avg','min','max','count','last')",
            name="ck_metric_definition_aggregation",
        ),
        schema="ai",
    )
    op.execute("REVOKE ALL ON ai.metric_definition FROM PUBLIC")
    op.execute("GRANT SELECT ON ai.metric_definition TO wattprint_ai")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ai.metric_definition TO wattprint_app")
    op.bulk_insert(
        sa.table(
            "metric_definition",
            sa.column("metric_code", sa.String),
            sa.column("label_vi", sa.String),
            sa.column("unit", sa.String),
            sa.column("aggregation", sa.String),
            sa.column("sql_query", sa.Text),
            schema="ai",
        ),
        [
            dict(
                zip(
                    ("metric_code", "label_vi", "unit", "aggregation", "sql_query"),
                    row,
                    strict=True,
                )
            )
            for row in METRICS
        ],
    )


def downgrade() -> None:
    op.execute("REVOKE ALL ON ai.metric_definition FROM wattprint_ai, wattprint_app")
    op.drop_table("metric_definition", schema="ai")
