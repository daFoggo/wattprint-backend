"""create unified minute energy fact with allocated household cost

Revision ID: c6a9e2f1b743
Revises: f39a7b2c5d18
"""

from alembic import op

revision = "c6a9e2f1b743"
down_revision = "f39a7b2c5d18"
branch_labels = None
depends_on = None

FACT_SQL = """
CREATE VIEW ai.fact_energy WITH (security_barrier = true) AS
WITH raw_channels AS (
    SELECT bucket, home_key, device_key, series_kind, metric_code, energy_wh,
           'reading'::text AS data_source, 1 AS source_priority
    FROM ai.fact_reading_1m
    WHERE series_kind IN ('plug', 'device') AND metric_code = 'power_w'
    UNION ALL
    SELECT bucket, home_key, device_key, series_kind, metric_code, energy_wh,
           'estimate'::text AS data_source, 2 AS source_priority
    FROM ai.fact_estimate_1m
    WHERE series_kind IN ('plug', 'device') AND metric_code = 'power_w'
), ranked_channels AS (
    SELECT r.*,
           row_number() OVER (
               PARTITION BY bucket, home_key, device_key, metric_code
               ORDER BY source_priority
           ) AS source_rank
    FROM raw_channels r
), channel_rows AS (
    SELECT r.bucket, r.home_key, r.device_key, r.series_kind, r.metric_code,
           r.energy_wh, r.data_source, h.billing_cycle_day, h.tariff_plan_key,
           CASE
             WHEN extract(day FROM (r.bucket AT TIME ZONE 'Asia/Ho_Chi_Minh'))::integer
                    >= h.billing_cycle_day
             THEN date_trunc('month', r.bucket AT TIME ZONE 'Asia/Ho_Chi_Minh')::date
                    + (h.billing_cycle_day - 1)
             ELSE (date_trunc('month', r.bucket AT TIME ZONE 'Asia/Ho_Chi_Minh')::date
                    - interval '1 month')::date + (h.billing_cycle_day - 1)
           END AS billing_cycle_start
    FROM ranked_channels r
    JOIN ai.dim_home h ON h.home_key = r.home_key
    WHERE r.source_rank = 1 AND NOT h.is_deleted
), channel_cumulative AS (
    SELECT c.*,
           sum(c.energy_wh) OVER (
               PARTITION BY c.home_key, c.device_key, c.metric_code, c.billing_cycle_start
               ORDER BY c.bucket ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
           ) AS cumulative_energy_wh
    FROM channel_rows c
), main_rows AS (
    SELECT r.bucket, r.home_key, r.energy_wh,
           h.tariff_plan_key, h.billing_cycle_day,
           CASE
             WHEN extract(day FROM (r.bucket AT TIME ZONE 'Asia/Ho_Chi_Minh'))::integer
                    >= h.billing_cycle_day
             THEN date_trunc('month', r.bucket AT TIME ZONE 'Asia/Ho_Chi_Minh')::date
                    + (h.billing_cycle_day - 1)
             ELSE (date_trunc('month', r.bucket AT TIME ZONE 'Asia/Ho_Chi_Minh')::date
                    - interval '1 month')::date + (h.billing_cycle_day - 1)
           END AS billing_cycle_start
    FROM ai.fact_reading_1m r
    JOIN ai.dim_home h ON h.home_key = r.home_key
    WHERE r.series_kind = 'main' AND r.metric_code = 'power_w' AND NOT h.is_deleted
), main_cumulative AS (
    SELECT m.*,
           sum(m.energy_wh) OVER (
               PARTITION BY m.home_key, m.billing_cycle_start
               ORDER BY m.bucket ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
           ) / 1000.0 AS cumulative_kwh
    FROM main_rows m
), home_cost_delta AS (
    SELECT m.bucket, m.home_key, m.billing_cycle_start,
           m.energy_wh AS home_energy_wh, v.id AS tariff_version_id,
           r.cost_delta AS home_cost_delta
    FROM main_cumulative m
    LEFT JOIN ai.dim_tariff_plan p ON p.tariff_plan_key = m.tariff_plan_key
    LEFT JOIN LATERAL (
        SELECT v.id, v.vat_rate
        FROM public.tb_tariff_version v
        WHERE v.plan_code = p.source_plan_code
          AND v.valid_from <= (m.bucket AT TIME ZONE 'Asia/Ho_Chi_Minh')::date
          AND (v.valid_to IS NULL OR
               v.valid_to >= (m.bucket AT TIME ZONE 'Asia/Ho_Chi_Minh')::date)
        ORDER BY v.valid_from DESC
        LIMIT 1
    ) v ON true
    LEFT JOIN LATERAL (
        SELECT sum(
            greatest(
                least(m.cumulative_kwh, coalesce(t.to_kwh, m.cumulative_kwh))
                - greatest(m.cumulative_kwh - m.energy_wh / 1000.0, t.from_kwh),
                0
            ) * t.price_per_kwh
        ) * (1 + v.vat_rate) AS cost_delta
        FROM public.tb_tariff_tier t
        WHERE t.version_id = v.id
    ) r ON true
), home_cost_checked AS (
    SELECT h.*,
           first_value(h.tariff_version_id) OVER (
               PARTITION BY h.home_key, h.billing_cycle_start
               ORDER BY h.bucket ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
           ) AS cycle_tariff_version_id
    FROM home_cost_delta h
), device_channel_totals AS (
    SELECT bucket, home_key, sum(energy_wh) AS channel_energy_wh
    FROM channel_cumulative
    GROUP BY bucket, home_key
)
SELECT c.bucket, c.home_key, c.device_key, c.series_kind, c.metric_code,
       c.data_source, c.energy_wh, c.cumulative_energy_wh, c.billing_cycle_start,
       h.home_energy_wh, d.channel_energy_wh,
       CASE WHEN d.channel_energy_wh > 0 AND h.home_energy_wh > 0
            THEN least(d.channel_energy_wh / h.home_energy_wh, 1)
            ELSE NULL END AS allocation_coverage,
       CASE WHEN d.channel_energy_wh > 0 AND h.home_energy_wh > 0
            THEN c.energy_wh / greatest(d.channel_energy_wh, h.home_energy_wh)
            ELSE NULL END AS allocation_share,
       CASE WHEN d.channel_energy_wh > 0 AND h.home_energy_wh > 0
                  AND h.home_cost_delta IS NOT NULL
                  AND h.tariff_version_id IS NOT DISTINCT FROM h.cycle_tariff_version_id
            THEN h.home_cost_delta * c.energy_wh
                 / greatest(d.channel_energy_wh, h.home_energy_wh)
            ELSE NULL END AS allocated_cost
FROM channel_cumulative c
LEFT JOIN home_cost_checked h ON h.home_key = c.home_key AND h.bucket = c.bucket
LEFT JOIN device_channel_totals d ON d.home_key = c.home_key AND d.bucket = c.bucket
"""


def upgrade() -> None:
    op.execute(FACT_SQL)
    op.execute("REVOKE ALL ON ai.fact_energy FROM PUBLIC")
    op.execute("GRANT SELECT ON ai.fact_energy TO wattprint_ai")
    op.execute(
        "COMMENT ON VIEW ai.fact_energy IS "
        "'Minute channel energy with billing-cycle cumulative kWh and allocated household cost.'"
    )


def downgrade() -> None:
    op.execute("REVOKE ALL ON ai.fact_energy FROM wattprint_ai")
    op.execute("DROP VIEW ai.fact_energy")
