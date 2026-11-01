"""catalog and core tables, seeded reference data

Revision ID: c3e5a7b9d1f2
Revises: b2d4f6a8c0e1
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "c3e5a7b9d1f2"
down_revision = "b2d4f6a8c0e1"
branch_labels = None
depends_on = None

UUID_PK = dict(server_default=sa.text("gen_random_uuid()"))
NOW = sa.text("now()")

METRICS = [
    ("power_w", "W", "mean"),
    ("energy_wh", "Wh", "energy"),
    ("reactive_power_var", "var", "mean"),
    ("voltage_v", "V", "mean"),
    ("current_a", "A", "mean"),
]

# code, label_vi, label_en, typical_watts, tip_text
DEVICE_TYPES = [
    ("ac", "Điều hòa", "Air conditioner", 1000,
     "Set it to 26 C or higher; each degree lower adds roughly 6 to 8 percent to its energy use."),
    ("fridge", "Tủ lạnh", "Fridge", 100,
     "Keep door seals clean and the fridge away from heat; a full fridge runs more efficiently."),
    ("freezer", "Tủ đông", "Freezer", 100,
     "Defrost regularly and keep it full; ice build-up makes the compressor work harder."),
    ("fridge_freezer", "Tủ lạnh có ngăn đông", "Fridge freezer", 120,
     "Leave a gap behind the unit for airflow and do not set the temperature colder than needed."),
    ("washing_machine", "Máy giặt", "Washing machine", 500,
     "Wash full loads in cold water when possible; heating the water is most of the energy."),
    ("washer_dryer", "Máy giặt sấy", "Washer dryer", 800,
     "Drying uses far more energy than washing; air-dry when the weather allows."),
    ("tumble_dryer", "Máy sấy quần áo", "Tumble dryer", 2000,
     "Clean the lint filter every load and spin clothes well before drying."),
    ("dishwasher", "Máy rửa bát", "Dishwasher", 1200,
     "Run only full loads and use the eco programme to cut heating energy."),
    ("television", "Ti vi", "Television", 100,
     "Lower the screen brightness and switch the TV off rather than leaving it on standby."),
    ("computer", "Máy tính", "Computer", 150,
     "Enable sleep mode and switch off the power strip when you are away for long."),
    ("microwave", "Lò vi sóng", "Microwave", 1000,
     "Microwaves are efficient for small portions; avoid using the oven to reheat them."),
    ("kettle", "Ấm đun nước", "Kettle", 2000,
     "Boil only the water you need; it is a short but high-power appliance."),
    ("toaster", "Máy nướng bánh mì", "Toaster", 800,
     "Short, high-power bursts; unplug it when not in use."),
    ("hifi", "Dàn âm thanh", "Hi-fi", 50,
     "Amplifiers draw power even when idle; turn them off at the switch."),
    ("electric_heater", "Máy sưởi điện", "Electric heater", 1500,
     "Heat the room you are in, not the whole house, and use a thermostat or timer."),
    ("router", "Bộ định tuyến Wi-Fi", "Wi-Fi router", 10,
     "Always on but low power; consider switching it off overnight if nothing needs it."),
    ("water_heater", "Bình nóng lạnh", "Water heater", 2500,
     "Lower the thermostat and switch it off when no one needs hot water."),
    ("electric_car", "Xe điện", "Electric car", 7000,
     "Charge outside peak hours and set a charge limit to avoid wasted energy."),
    ("lights", "Đèn chiếu sáng", "Lights", 60,
     "Switch to LED bulbs and turn lights off in empty rooms."),
    ("oven", "Lò nướng", "Oven", 2000,
     "Avoid opening the door while cooking and use the residual heat at the end."),
    ("always_on", "Thiết bị luôn bật", "Always on", None,
     "Standby and background load: the energy your home uses even when nothing seems to be on."),
    ("other", "Khác", "Other", None,
     "Energy that could not be attributed to a specific device."),
]


def _lit(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, int):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"


def _seed(table: str, cols: tuple[str, ...], pk: str, rows) -> None:
    values = ", ".join("(" + ", ".join(_lit(v) for v in r) + ")" for r in rows)
    op.execute(
        f"INSERT INTO {table} ({', '.join(cols)}) VALUES {values} "
        f"ON CONFLICT ({pk}) DO NOTHING"
    )


def upgrade() -> None:
    op.create_table(
        "metric",
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("unit", sa.String(16), nullable=False),
        sa.Column("aggregation", sa.String(16), nullable=False),
        sa.PrimaryKeyConstraint("event_type", name="pk_metric"),
        sa.CheckConstraint("aggregation IN ('mean','max','energy')", name="ck_metric_aggregation"),
        schema="catalog",
    )
    op.create_table(
        "device_type",
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("label_vi", sa.String(128), nullable=False),
        sa.Column("label_en", sa.String(128), nullable=False),
        sa.Column("typical_watts", sa.Integer(), nullable=True),
        sa.Column("tip_text", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("code", name="pk_device_type"),
        schema="catalog",
    )
    _seed("catalog.metric", ("event_type", "unit", "aggregation"), "event_type", METRICS)
    _seed(
        "catalog.device_type",
        ("code", "label_vi", "label_en", "typical_watts", "tip_text"),
        "code",
        DEVICE_TYPES,
    )

    op.create_table(
        "home",
        sa.Column("id", sa.Uuid(), nullable=False, **UUID_PK),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("postal_code", sa.String(16), nullable=True),
        sa.Column("province_code", sa.String(16), nullable=True),
        sa.Column("home_type", sa.String(16), nullable=True),
        sa.Column("floor_area_m2", sa.Numeric(8, 2), nullable=True),
        sa.Column("year_built", sa.SmallInteger(), nullable=True),
        sa.Column("occupants", sa.SmallInteger(), nullable=True),
        sa.Column("timezone", sa.String(64), nullable=False, server_default="Asia/Ho_Chi_Minh"),
        sa.Column("tariff_plan_code", sa.String(64), nullable=True),
        sa.Column("billing_cycle_day", sa.SmallInteger(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.PrimaryKeyConstraint("id", name="pk_home"),
        sa.CheckConstraint("home_type IN ('apartment','house','other')", name="ck_home_home_type"),
        sa.CheckConstraint("billing_cycle_day BETWEEN 1 AND 28", name="ck_home_billing_cycle_day"),
        sa.CheckConstraint("timezone = 'Asia/Ho_Chi_Minh'", name="ck_home_timezone"),
        schema="core",
    )
    op.create_table(
        "home_member",
        sa.Column("home_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.PrimaryKeyConstraint("home_id", "user_id", name="pk_home_member"),
        sa.ForeignKeyConstraint(
            ["home_id"], ["core.home.id"], name="fk_home_member_home_id_home", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["public.users.id"],
            name="fk_home_member_user_id_users",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("user_id", name="uq_home_member_user_id"),
        sa.CheckConstraint("role IN ('owner','member')", name="ck_home_member_role"),
        schema="core",
    )
    op.create_table(
        "home_invite",
        sa.Column("id", sa.Uuid(), nullable=False, **UUID_PK),
        sa.Column("home_id", sa.Uuid(), nullable=False),
        sa.Column("code_hash", sa.String(128), nullable=False),
        sa.Column("role", sa.String(16), nullable=False, server_default="member"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_by", sa.Uuid(), nullable=True),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_home_invite"),
        sa.ForeignKeyConstraint(
            ["home_id"], ["core.home.id"], name="fk_home_invite_home_id_home", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["used_by"], ["public.users.id"], name="fk_home_invite_used_by_users"
        ),
        sa.CheckConstraint("role IN ('owner','member')", name="ck_home_invite_role"),
        schema="core",
    )
    op.create_table(
        "meter",
        sa.Column("id", sa.Uuid(), nullable=False, **UUID_PK),
        sa.Column("serial", sa.String(64), nullable=False),
        sa.Column("home_id", sa.Uuid(), nullable=True),
        sa.Column("claim_code_hash", sa.String(128), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("firmware", sa.String(64), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="new"),
        sa.PrimaryKeyConstraint("id", name="pk_meter"),
        sa.ForeignKeyConstraint(["home_id"], ["core.home.id"], name="fk_meter_home_id_home"),
        sa.UniqueConstraint("serial", name="uq_meter_serial"),
        sa.CheckConstraint("status IN ('new','active','retired')", name="ck_meter_status"),
        schema="core",
    )
    op.create_table(
        "device",
        sa.Column("id", sa.Uuid(), nullable=False, **UUID_PK),
        sa.Column("home_id", sa.Uuid(), nullable=False),
        sa.Column("device_type_code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("room", sa.String(128), nullable=True),
        sa.Column("origin", sa.String(16), nullable=False),
        sa.Column("show_on_timeline", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("active_from", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("active_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("merged_into_id", sa.Uuid(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.PrimaryKeyConstraint("id", name="pk_device"),
        sa.ForeignKeyConstraint(
            ["home_id"], ["core.home.id"], name="fk_device_home_id_home", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["device_type_code"],
            ["catalog.device_type.code"],
            name="fk_device_device_type_code_device_type",
        ),
        sa.ForeignKeyConstraint(
            ["merged_into_id"], ["core.device.id"], name="fk_device_merged_into_id_device"
        ),
        sa.CheckConstraint("origin IN ('nilm','plug','manual')", name="ck_device_origin"),
        sa.CheckConstraint(
            "active_to IS NULL OR active_to > active_from", name="ck_device_validity_range"
        ),
        schema="core",
    )
    op.create_table(
        "device_alert_rule",
        sa.Column("id", sa.Uuid(), nullable=False, **UUID_PK),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column(
            "params",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.PrimaryKeyConstraint("id", name="pk_device_alert_rule"),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["core.device.id"],
            name="fk_device_alert_rule_device_id_device",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("kind IN ('on','off','custom')", name="ck_device_alert_rule_kind"),
        schema="core",
    )


def downgrade() -> None:
    op.drop_table("device_alert_rule", schema="core")
    op.drop_table("device", schema="core")
    op.drop_table("meter", schema="core")
    op.drop_table("home_invite", schema="core")
    op.drop_table("home_member", schema="core")
    op.drop_table("home", schema="core")
    op.drop_table("device_type", schema="catalog")
    op.drop_table("metric", schema="catalog")
