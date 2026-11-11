"""initialize home and device dimensions for the AI data mart

Revision ID: a4c7e1d93b62
Revises: b7d9e3a1c5f8
"""

import sqlalchemy as sa

from alembic import op

revision = "a4c7e1d93b62"
down_revision = "b7d9e3a1c5f8"
branch_labels = None
depends_on = None

UUID7 = sa.text("uuidv7()")

def upgrade() -> None:
    op.execute("GRANT USAGE ON SCHEMA ai TO wattprint_app")

    op.create_table(
        "dim_home",
        sa.Column("home_key", sa.Uuid(), server_default=UUID7, nullable=False),
        sa.Column("source_home_id", sa.Uuid(), nullable=False),
        sa.Column("province_code", sa.String(16)),
        sa.Column("home_type", sa.String(16)),
        sa.Column("floor_area_m2", sa.Numeric(8, 2)),
        sa.Column("year_built", sa.SmallInteger()),
        sa.Column("occupants", sa.SmallInteger()),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("tariff_plan_key", sa.Uuid()),
        sa.Column("billing_cycle_day", sa.SmallInteger(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("home_key", name="pk_dim_home"),
        sa.UniqueConstraint("source_home_id", name="uq_dim_home_source_home_id"),
        sa.ForeignKeyConstraint(
            ["tariff_plan_key"],
            ["ai.dim_tariff_plan.tariff_plan_key"],
            name="fk_dim_home_tariff_plan",
        ),
        schema="ai",
    )
    op.create_table(
        "dim_device",
        sa.Column("device_key", sa.Uuid(), server_default=UUID7, nullable=False),
        sa.Column("source_device_id", sa.Uuid(), nullable=False),
        sa.Column("home_key", sa.Uuid(), nullable=False),
        sa.Column("device_type_code", sa.String(64), nullable=False),
        sa.Column("device_type_label_vi", sa.String(128), nullable=False),
        sa.Column("device_type_label_en", sa.String(128), nullable=False),
        sa.Column("typical_watts", sa.Integer()),
        sa.Column("device_type_tip", sa.Text()),
        sa.Column("device_name", sa.String(255), nullable=False),
        sa.Column("room", sa.String(128)),
        sa.Column("origin", sa.String(16), nullable=False),
        sa.Column("show_on_timeline", sa.Boolean(), nullable=False),
        sa.Column("active_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("active_to", sa.DateTime(timezone=True)),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("device_key", name="pk_dim_device"),
        sa.UniqueConstraint("source_device_id", name="uq_dim_device_source_device_id"),
        sa.ForeignKeyConstraint(["home_key"], ["ai.dim_home.home_key"], name="fk_dim_device_home"),
        schema="ai",
    )

    op.execute(
        """
        CREATE FUNCTION ai.sync_dim_home() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, ai, public AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                UPDATE ai.dim_home
                   SET is_deleted = true, updated_at = now()
                 WHERE source_home_id = OLD.id;
                RETURN OLD;
            END IF;

            INSERT INTO ai.dim_home (
                source_home_id, province_code, home_type, floor_area_m2, year_built,
                occupants, timezone, tariff_plan_key, billing_cycle_day, is_deleted, updated_at
            ) VALUES (
                NEW.id, NEW.province_code, NEW.home_type, NEW.floor_area_m2, NEW.year_built,
                NEW.occupants, NEW.timezone,
                (SELECT tariff_plan_key FROM ai.dim_tariff_plan
                 WHERE source_plan_code = NEW.tariff_plan_code),
                NEW.billing_cycle_day, false, now()
            )
            ON CONFLICT (source_home_id) DO UPDATE SET
                province_code = EXCLUDED.province_code,
                home_type = EXCLUDED.home_type,
                floor_area_m2 = EXCLUDED.floor_area_m2,
                year_built = EXCLUDED.year_built,
                occupants = EXCLUDED.occupants,
                timezone = EXCLUDED.timezone,
                tariff_plan_key = EXCLUDED.tariff_plan_key,
                billing_cycle_day = EXCLUDED.billing_cycle_day,
                is_deleted = false,
                updated_at = now();
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION ai.sync_dim_device() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, ai, public AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                UPDATE ai.dim_device
                   SET is_deleted = true, updated_at = now()
                 WHERE source_device_id = OLD.id;
                RETURN OLD;
            END IF;

            INSERT INTO ai.dim_device (
                source_device_id, home_key, device_type_code, device_type_label_vi,
                device_type_label_en, typical_watts, device_type_tip, device_name, room,
                origin, show_on_timeline, active_from, active_to, deleted_at,
                is_deleted, updated_at
            )
            SELECT NEW.id, h.home_key, NEW.device_type_code, t.label_vi, t.label_en,
                   t.typical_watts, t.tip_text, NEW.name, NEW.room, NEW.origin,
                   NEW.show_on_timeline, NEW.active_from, NEW.active_to, NEW.deleted_at,
                   false, now()
              FROM ai.dim_home h
              JOIN public.cat_device_type t ON t.code = NEW.device_type_code
             WHERE h.source_home_id = NEW.home_id
            ON CONFLICT (source_device_id) DO UPDATE SET
                home_key = EXCLUDED.home_key,
                device_type_code = EXCLUDED.device_type_code,
                device_type_label_vi = EXCLUDED.device_type_label_vi,
                device_type_label_en = EXCLUDED.device_type_label_en,
                typical_watts = EXCLUDED.typical_watts,
                device_type_tip = EXCLUDED.device_type_tip,
                device_name = EXCLUDED.device_name,
                room = EXCLUDED.room,
                origin = EXCLUDED.origin,
                show_on_timeline = EXCLUDED.show_on_timeline,
                active_from = EXCLUDED.active_from,
                active_to = EXCLUDED.active_to,
                deleted_at = EXCLUDED.deleted_at,
                is_deleted = false,
                updated_at = now();
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION ai.sync_dim_device_type() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, ai, public AS $$
        BEGIN
            UPDATE ai.dim_device
               SET device_type_label_vi = NEW.label_vi,
                   device_type_label_en = NEW.label_en,
                   typical_watts = NEW.typical_watts,
                   device_type_tip = NEW.tip_text,
                   updated_at = now()
             WHERE device_type_code = NEW.code;
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_sync_ai_dim_home AFTER INSERT OR UPDATE OR DELETE "
        "ON public.tb_home FOR EACH ROW EXECUTE FUNCTION ai.sync_dim_home()"
    )
    op.execute(
        "CREATE TRIGGER trg_sync_ai_dim_device AFTER INSERT OR UPDATE OR DELETE "
        "ON public.tb_device FOR EACH ROW EXECUTE FUNCTION ai.sync_dim_device()"
    )
    op.execute(
        "CREATE TRIGGER trg_sync_ai_dim_device_type AFTER UPDATE "
        "ON public.cat_device_type FOR EACH ROW EXECUTE FUNCTION ai.sync_dim_device_type()"
    )
    op.execute(
        "REVOKE ALL ON FUNCTION ai.sync_dim_home(), ai.sync_dim_device(), "
        "ai.sync_dim_device_type() FROM PUBLIC"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION ai.sync_dim_home(), ai.sync_dim_device(), "
        "ai.sync_dim_device_type() TO wattprint_app"
    )

    op.execute(
        """
        INSERT INTO ai.dim_home (
            source_home_id, province_code, home_type, floor_area_m2, year_built,
            occupants, timezone, tariff_plan_key, billing_cycle_day
        )
        SELECT h.id, h.province_code, h.home_type, h.floor_area_m2, h.year_built,
               h.occupants, h.timezone, p.tariff_plan_key, h.billing_cycle_day
        FROM public.tb_home AS h
        LEFT JOIN ai.dim_tariff_plan AS p ON p.source_plan_code = h.tariff_plan_code
        """
    )
    op.execute(
        """
        INSERT INTO ai.dim_device (
            source_device_id, home_key, device_type_code, device_type_label_vi,
            device_type_label_en, typical_watts, device_type_tip, device_name, room,
            origin, show_on_timeline, active_from, active_to, deleted_at
        )
        SELECT d.id, h.home_key, d.device_type_code, t.label_vi, t.label_en,
               t.typical_watts, t.tip_text, d.name, d.room, d.origin,
               d.show_on_timeline, d.active_from, d.active_to, d.deleted_at
        FROM public.tb_device AS d
        JOIN ai.dim_home AS h ON h.source_home_id = d.home_id
        JOIN public.cat_device_type AS t ON t.code = d.device_type_code
        """
    )

    op.execute("REVOKE ALL ON ai.dim_home, ai.dim_device FROM PUBLIC")
    op.execute("GRANT SELECT ON ai.dim_home, ai.dim_device TO wattprint_ai")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON ai.dim_home, ai.dim_device TO wattprint_app"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER trg_sync_ai_dim_device_type ON public.cat_device_type")
    op.execute("DROP TRIGGER trg_sync_ai_dim_device ON public.tb_device")
    op.execute("DROP TRIGGER trg_sync_ai_dim_home ON public.tb_home")
    op.execute("DROP FUNCTION ai.sync_dim_device_type()")
    op.execute("DROP FUNCTION ai.sync_dim_device()")
    op.execute("DROP FUNCTION ai.sync_dim_home()")
    op.execute("REVOKE ALL ON ai.dim_home, ai.dim_device FROM wattprint_ai, wattprint_app")
    op.drop_table("dim_device", schema="ai")
    op.drop_table("dim_home", schema="ai")
    op.execute("REVOKE USAGE ON SCHEMA ai FROM wattprint_app")
