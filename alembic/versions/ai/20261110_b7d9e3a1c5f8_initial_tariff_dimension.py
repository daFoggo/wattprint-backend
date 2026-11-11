"""create tariff-plan dimension for the AI data mart

Revision ID: b7d9e3a1c5f8
Revises: 8c2f6a1d4b90
"""

import sqlalchemy as sa

from alembic import op

revision = "b7d9e3a1c5f8"
down_revision = "8c2f6a1d4b90"
branch_labels = None
depends_on = None

UUID7 = sa.text("uuidv7()")


def upgrade() -> None:
    op.execute("GRANT USAGE ON SCHEMA ai TO wattprint_app")
    op.create_table(
        "dim_tariff_plan",
        sa.Column("tariff_plan_key", sa.Uuid(), server_default=UUID7, nullable=False),
        sa.Column("source_plan_code", sa.String(64), nullable=False),
        sa.Column("plan_name", sa.Text(), nullable=False),
        sa.Column("currency", sa.Text(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("tariff_plan_key", name="pk_dim_tariff_plan"),
        sa.UniqueConstraint("source_plan_code", name="uq_dim_tariff_plan_source_code"),
        schema="ai",
    )
    op.execute(
        """
        CREATE FUNCTION ai.sync_dim_tariff_plan() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, ai, public AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                UPDATE ai.dim_tariff_plan
                   SET is_deleted = true, updated_at = now()
                 WHERE source_plan_code = OLD.code;
                RETURN OLD;
            END IF;

            INSERT INTO ai.dim_tariff_plan (
                source_plan_code, plan_name, currency, is_deleted, updated_at
            ) VALUES (NEW.code, NEW.name, NEW.currency, false, now())
            ON CONFLICT (source_plan_code) DO UPDATE SET
                plan_name = EXCLUDED.plan_name,
                currency = EXCLUDED.currency,
                is_deleted = false,
                updated_at = now();
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_sync_ai_dim_tariff_plan AFTER INSERT OR UPDATE OR DELETE "
        "ON public.tb_tariff_plan FOR EACH ROW EXECUTE FUNCTION ai.sync_dim_tariff_plan()"
    )
    op.execute("REVOKE ALL ON FUNCTION ai.sync_dim_tariff_plan() FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION ai.sync_dim_tariff_plan() TO wattprint_app")
    op.execute(
        """
        INSERT INTO ai.dim_tariff_plan (source_plan_code, plan_name, currency)
        SELECT code, name, currency FROM public.tb_tariff_plan
        """
    )
    op.execute("REVOKE ALL ON ai.dim_tariff_plan FROM PUBLIC")
    op.execute("GRANT SELECT ON ai.dim_tariff_plan TO wattprint_ai")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ai.dim_tariff_plan TO wattprint_app")


def downgrade() -> None:
    op.execute("DROP TRIGGER trg_sync_ai_dim_tariff_plan ON public.tb_tariff_plan")
    op.execute("DROP FUNCTION ai.sync_dim_tariff_plan()")
    op.execute("REVOKE ALL ON ai.dim_tariff_plan FROM wattprint_ai, wattprint_app")
    op.drop_table("dim_tariff_plan", schema="ai")
    op.execute("REVOKE USAGE ON SCHEMA ai FROM wattprint_app")
