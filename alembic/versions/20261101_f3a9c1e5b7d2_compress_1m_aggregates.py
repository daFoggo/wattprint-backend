"""compress the 1 minute continuous aggregates and add their compression policies

Measured on a scratch copy of one month of House 1 (docs/database-audit.md, 10b; not on the full
audit data): reading_1m and device_estimate_1m are about 150 bytes/row uncompressed and 6-8
bytes/row compressed (19x and 23x). On the audit data the uncompressed 1 m aggregates were three
times the size of the compressed raw tables. segmentby series_id / orderby bucket DESC mirrors
the raw tables.

Real-time aggregation stays on (materialized_only = false): reads over compressed chunks, late-data
refreshes of compressed ranges and the 1 h / 1 d aggregates built on top of the compressed 1 m one
are covered by tests/db/test_cagg_compression.py. The policy compresses chunks older than 14 days,
which must stay above the 1 m refresh policy start_offset (7 days): a refresh policy must not
find its window already converted (TimescaleDB docs, "compress continuous aggregates").

The downgrade decompresses every compressed 1 m chunk inside the migration transaction: on a
large database that needs the disk space of the uncompressed chunks and holds locks for the
duration, so plan it as a maintenance window.

Revision ID: f3a9c1e5b7d2
Revises: 4d7b1e9a3c52
"""

from alembic import op

revision = "f3a9c1e5b7d2"
down_revision = "4d7b1e9a3c52"
branch_labels = None
depends_on = None

FAMILIES = ("reading", "device_estimate")

# Task 4 body (c8a4e1f7b295), restored on downgrade.
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

# V2 plus a compression policy on each 1 m aggregate (compress_after > refresh start_offset).
SET_POLICIES_V3 = """
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
            PERFORM add_compression_policy(format('energy.%s_1m', fam), INTERVAL '14 days',
                                           if_not_exists => true);
            PERFORM add_retention_policy(format('energy.%s_1m', fam), INTERVAL '400 days',
                                         if_not_exists => true);
        END LOOP;
    ELSE
        FOREACH fam IN ARRAY ARRAY['reading', 'device_estimate'] LOOP
            PERFORM remove_retention_policy(format('energy.%s_1m', fam), if_exists => true);
            PERFORM remove_compression_policy(format('energy.%s_1m', fam), if_exists => true);
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


def upgrade() -> None:
    for fam in FAMILIES:
        op.execute(
            f"ALTER MATERIALIZED VIEW energy.{fam}_1m SET (timescaledb.compress = true, "
            "timescaledb.compress_segmentby = 'series_id', "
            "timescaledb.compress_orderby = 'bucket DESC')"
        )
    op.execute(SET_POLICIES_V3)
    # Policies that exist (set_policies(true) was run) get the new compression policies at once.
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM timescaledb_information.jobs "
        "WHERE proc_name = 'policy_compression' AND hypertable_name = 'reading') THEN "
        "PERFORM ops.set_policies(true); END IF; END $$"
    )


def downgrade() -> None:
    for fam in FAMILIES:
        op.execute(f"SELECT remove_compression_policy('energy.{fam}_1m', if_exists => true)")
    # Decompress every compressed chunk of the two aggregates, then switch compression off.
    op.execute(
        """
        DO $$
        DECLARE ch regclass;
        BEGIN
            FOR ch IN
                SELECT format('%I.%I', c.chunk_schema, c.chunk_name)::regclass
                FROM timescaledb_information.chunks c
                JOIN timescaledb_information.continuous_aggregates a
                  ON a.materialization_hypertable_schema = c.hypertable_schema
                 AND a.materialization_hypertable_name = c.hypertable_name
                WHERE a.view_schema = 'energy'
                  AND a.view_name IN ('reading_1m', 'device_estimate_1m')
                  AND c.is_compressed
            LOOP
                PERFORM decompress_chunk(ch);
            END LOOP;
        END $$
        """
    )
    for fam in FAMILIES:
        op.execute(f"ALTER MATERIALIZED VIEW energy.{fam}_1m SET (timescaledb.compress = false)")
    op.execute(SET_POLICIES_V2)
