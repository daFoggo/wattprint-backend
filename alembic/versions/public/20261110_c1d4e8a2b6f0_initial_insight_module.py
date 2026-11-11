"""initial insight module: alerts, forecasts, cohorts and device cycles

Revision ID: c1d4e8a2b6f0
Revises: d7b3f9a2c6e4
"""

import sqlalchemy as sa

from alembic import op

revision = "c1d4e8a2b6f0"
down_revision = "d7b3f9a2c6e4"
branch_labels = None
depends_on = None

UUID7 = sa.text("uuidv7()")

SERIES_DAILY_COVERAGE = """
CREATE VIEW public.series_daily_coverage AS
SELECT f.series_id,
       g.day,
       coalesce(r.covered_minutes, 0)::bigint AS covered_minutes,
       1440 AS expected_minutes,
       coalesce(r.covered_minutes, 0)::numeric / 1440 AS coverage
FROM (SELECT series_id,
             (min(bucket) AT TIME ZONE 'Asia/Ho_Chi_Minh')::date AS first_day
      FROM public.reading_1d
      GROUP BY series_id) f
CROSS JOIN LATERAL (
    SELECT d::date AS day
    FROM generate_series(f.first_day::timestamp,
                         (now() AT TIME ZONE 'Asia/Ho_Chi_Minh')::date::timestamp,
                         INTERVAL '1 day') d
) g
LEFT JOIN public.reading_1d r
       ON r.series_id = f.series_id
      AND (r.bucket AT TIME ZONE 'Asia/Ho_Chi_Minh')::date = g.day
"""

SERIES_DAILY_COVERAGE_COMMENT = (
    "One row per series per local (Asia/Ho_Chi_Minh) day, from the series' first reading_1d "
    "bucket through today; days without readings show covered_minutes 0 and coverage 0. "
    "Limitation: a series with no readings at all has no history and is not listed. Today's "
    "row is always partial (real-time aggregation is on, and the day is not over)."
)

def _comment_view(view: str, text: str) -> None:
    # COMMENT does not accept bind parameters, so the literal is quoted by hand.
    op.execute(sa.text("COMMENT ON VIEW " + view + " IS '" + text.replace("'", "''") + "'"))


def _uuid_pk() -> sa.Column:
    return sa.Column("id", sa.Uuid, server_default=UUID7, primary_key=True)


def _fk(col: str, target: str, ondelete: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint([col], [target], ondelete=ondelete)

def _insight() -> None:
    op.execute(
        """
        CREATE TABLE public.tb_device_cycle (
            home_id uuid NOT NULL,
            device_id uuid NOT NULL,
            start_ts timestamptz NOT NULL,
            end_ts timestamptz NOT NULL,
            energy_wh double precision NOT NULL,
            peak_w real NOT NULL,
            CONSTRAINT pk_device_cycle PRIMARY KEY (device_id, start_ts),
            CONSTRAINT fk_device_cycle_home_id_home FOREIGN KEY (home_id)
                REFERENCES public.tb_home (id) ON DELETE CASCADE,
            CONSTRAINT fk_device_cycle_device_id_device FOREIGN KEY (device_id)
                REFERENCES public.tb_device (id) ON DELETE CASCADE,
            CONSTRAINT ck_device_cycle_range CHECK (end_ts > start_ts)
        )
        """
    )
    op.execute(
        "SELECT create_hypertable('public.tb_device_cycle', "
        "by_range('start_ts', INTERVAL '30 days'), create_default_indexes => false)"
    )

    op.create_table(
        "tb_alert",
        _uuid_pk(),
        sa.Column("home_id", sa.Uuid, nullable=False),
        sa.Column("device_id", sa.Uuid),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "payload",
            sa.dialects.postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("status", sa.String(16), nullable=False, server_default="open"),
        _fk("home_id", "public.tb_home.id", "CASCADE"),
        _fk("device_id", "public.tb_device.id", "SET NULL"),
        sa.CheckConstraint("severity IN ('info','warning','critical')", name="severity"),
        sa.CheckConstraint("status IN ('open','acknowledged','resolved')", name="status"),
        schema="public",
    )
    op.create_table(
        "tb_forecast_snapshot",
        _uuid_pk(),
        sa.Column("home_id", sa.Uuid, nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("horizon_date", sa.Date, nullable=False),
        sa.Column("kwh", sa.Numeric(12, 3), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("tier_cross_date", sa.Date),
        sa.Column("model_version", sa.Text, nullable=False),
        _fk("home_id", "public.tb_home.id", "CASCADE"),
        sa.UniqueConstraint("home_id", "generated_at", "horizon_date"),
        schema="public",
    )

    op.create_table(
        "tb_cohort_stat",
        sa.Column("cohort_key", sa.Text, nullable=False),
        sa.Column("period", sa.Date, nullable=False),
        sa.Column("p10_w", sa.Numeric(10, 2), nullable=False),
        sa.Column("p33_w", sa.Numeric(10, 2), nullable=False),
        sa.Column("p66_w", sa.Numeric(10, 2), nullable=False),
        sa.Column("p90_w", sa.Numeric(10, 2), nullable=False),
        sa.Column("n_homes", sa.Integer, nullable=False),
        sa.PrimaryKeyConstraint("cohort_key", "period"),
        sa.CheckConstraint("n_homes >= 10", name="min_size"),
        schema="public",
    )

def upgrade() -> None:
    _insight()
    op.execute(SERIES_DAILY_COVERAGE)
    _comment_view("public.series_daily_coverage", SERIES_DAILY_COVERAGE_COMMENT)


def downgrade() -> None:
    op.execute("DROP VIEW public.series_daily_coverage")
    for table in ("tb_cohort_stat", "tb_forecast_snapshot", "tb_alert", "tb_device_cycle"):
        op.drop_table(table, schema="public")
