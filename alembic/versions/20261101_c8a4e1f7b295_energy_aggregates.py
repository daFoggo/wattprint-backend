"""continuous aggregates and aggregate policies

Revision ID: c8a4e1f7b295
Revises: b9d2e6f0a384
"""

from alembic import op

revision = "c8a4e1f7b295"
down_revision = "b9d2e6f0a384"
branch_labels = None
depends_on = None

FAMILIES = ("reading", "device_estimate")

# Task 3 body, restored on downgrade.
SET_POLICIES_V1 = """
CREATE OR REPLACE FUNCTION ops.set_policies(enabled boolean) RETURNS void
LANGUAGE plpgsql
SET search_path = public, pg_catalog AS $$
BEGIN
    IF enabled THEN
        PERFORM add_compression_policy('energy.reading', INTERVAL '2 days', if_not_exists => true);
        PERFORM add_compression_policy('energy.device_estimate', INTERVAL '2 days',
                                       if_not_exists => true);
        PERFORM add_retention_policy('energy.reading', INTERVAL '400 days', if_not_exists => true);
        PERFORM add_retention_policy('energy.device_estimate', INTERVAL '400 days',
                                     if_not_exists => true);
    ELSE
        PERFORM remove_compression_policy('energy.reading', if_exists => true);
        PERFORM remove_compression_policy('energy.device_estimate', if_exists => true);
        PERFORM remove_retention_policy('energy.reading', if_exists => true);
        PERFORM remove_retention_policy('energy.device_estimate', if_exists => true);
    END IF;
END
$$
"""

# Note: if_not_exists does not update the offsets of an existing policy; a later revision that
# changes them must remove and re-add the policy.
SET_POLICIES_V2 = """
CREATE OR REPLACE FUNCTION ops.set_policies(enabled boolean) RETURNS void
LANGUAGE plpgsql
SET search_path = public, pg_catalog AS $$
DECLARE
    fam text;
BEGIN
    IF enabled THEN
        PERFORM add_compression_policy('energy.reading', INTERVAL '2 days', if_not_exists => true);
        PERFORM add_compression_policy('energy.device_estimate', INTERVAL '2 days',
                                       if_not_exists => true);
        PERFORM add_retention_policy('energy.reading', INTERVAL '400 days', if_not_exists => true);
        PERFORM add_retention_policy('energy.device_estimate', INTERVAL '400 days',
                                     if_not_exists => true);
        FOREACH fam IN ARRAY ARRAY['reading', 'device_estimate'] LOOP
            PERFORM add_continuous_aggregate_policy(
                format('energy.%s_1m', fam), start_offset => INTERVAL '7 days',
                end_offset => INTERVAL '1 minute', schedule_interval => INTERVAL '1 minute',
                if_not_exists => true);
            PERFORM add_continuous_aggregate_policy(
                format('energy.%s_1h', fam), start_offset => INTERVAL '30 days',
                end_offset => INTERVAL '1 hour', schedule_interval => INTERVAL '1 hour',
                if_not_exists => true);
            PERFORM add_continuous_aggregate_policy(
                format('energy.%s_1d', fam), start_offset => INTERVAL '60 days',
                end_offset => INTERVAL '1 hour', schedule_interval => INTERVAL '1 hour',
                if_not_exists => true);
            PERFORM add_retention_policy(format('energy.%s_1m', fam), INTERVAL '400 days',
                                         if_not_exists => true);
        END LOOP;
    ELSE
        FOREACH fam IN ARRAY ARRAY['reading', 'device_estimate'] LOOP
            PERFORM remove_retention_policy(format('energy.%s_1m', fam), if_exists => true);
            PERFORM remove_continuous_aggregate_policy(format('energy.%s_1d', fam),
                                                       if_exists => true);
            PERFORM remove_continuous_aggregate_policy(format('energy.%s_1h', fam),
                                                       if_exists => true);
            PERFORM remove_continuous_aggregate_policy(format('energy.%s_1m', fam),
                                                       if_exists => true);
        END LOOP;
        PERFORM remove_compression_policy('energy.reading', if_exists => true);
        PERFORM remove_compression_policy('energy.device_estimate', if_exists => true);
        PERFORM remove_retention_policy('energy.reading', if_exists => true);
        PERFORM remove_retention_policy('energy.device_estimate', if_exists => true);
    END IF;
END
$$
"""

def _views(family: str) -> list[str]:
    quality = "WHERE quality & 1 = 0" if family == "reading" else ""
    return [
        f"""
        CREATE MATERIALIZED VIEW energy.{family}_1m WITH (timescaledb.continuous) AS
        SELECT time_bucket('1 minute', ts) AS bucket,
               series_id,
               avg(value)::double precision AS avg_w,
               min(value) AS min_w,
               max(value) AS max_w,
               last(value, ts) AS last_w,
               count(*) AS n,
               avg(value) * 60.0 / 3600.0 AS energy_wh
        FROM energy.{family} {quality}
        GROUP BY 1, 2
        WITH NO DATA
        """,
        f"""
        CREATE MATERIALIZED VIEW energy.{family}_1h WITH (timescaledb.continuous) AS
        SELECT time_bucket('1 hour', bucket) AS bucket,
               series_id,
               sum(avg_w * n) / sum(n) AS avg_w,
               min(min_w) AS min_w,
               max(max_w) AS max_w,
               last(last_w, bucket) AS last_w,
               sum(n)::bigint AS n,
               sum(energy_wh) AS energy_wh,
               count(*) AS covered_minutes
        FROM energy.{family}_1m
        GROUP BY 1, 2
        WITH NO DATA
        """,
        f"""
        CREATE MATERIALIZED VIEW energy.{family}_1d WITH (timescaledb.continuous) AS
        SELECT time_bucket('1 day', bucket, 'Asia/Ho_Chi_Minh') AS bucket,
               series_id,
               sum(avg_w * n) / sum(n) AS avg_w,
               min(min_w) AS min_w,
               max(max_w) AS max_w,
               last(last_w, bucket) AS last_w,
               sum(n)::bigint AS n,
               sum(energy_wh) AS energy_wh,
               sum(covered_minutes)::bigint AS covered_minutes
        FROM energy.{family}_1h
        GROUP BY 1, 2
        WITH NO DATA
        """,
    ]


def upgrade() -> None:
    for family in FAMILIES:
        for ddl in _views(family):
            op.execute(ddl)
        for res in ("1m", "1h", "1d"):
            op.execute(
                f"ALTER MATERIALIZED VIEW energy.{family}_{res} "
                "SET (timescaledb.materialized_only = false)"
            )
    op.execute(SET_POLICIES_V2)
    op.execute("SELECT ops.set_policies(true)")


def downgrade() -> None:
    # Remove only the aggregate policies: the raw-table compression/retention policies belong
    # to the previous revision and must survive the downgrade.
    for family in FAMILIES:
        op.execute(f"SELECT remove_retention_policy('energy.{family}_1m', if_exists => true)")
        for res in ("1d", "1h", "1m"):
            op.execute(
                f"SELECT remove_continuous_aggregate_policy('energy.{family}_{res}', "
                "if_exists => true)"
            )
    op.execute(SET_POLICIES_V1)
    for family in FAMILIES:
        for res in ("1d", "1h", "1m"):
            op.execute(f"DROP MATERIALIZED VIEW energy.{family}_{res}")
