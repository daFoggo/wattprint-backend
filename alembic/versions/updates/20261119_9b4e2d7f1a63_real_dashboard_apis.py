"""real dashboard APIs: provinces, user preferences, alert upserts, copilot replies, mail log

Revision ID: 9b4e2d7f1a63
Revises: 3e8b6d2f9a14
"""

import sqlalchemy as sa

from alembic import op

revision = "9b4e2d7f1a63"
down_revision = "3e8b6d2f9a14"
branch_labels = None
depends_on = None

APP = "wattprint_app"
COPILOT = "wattprint_copilot_ro"
NOW = sa.text("now()")
ALERT_KINDS = ("longer_than_usual", "standby_high", "tier_near", "unexplained_load")

# The 34 province-level units since 1 July 2025 (Resolution 202/2025/QH15), with the code each kept
# and the coordinates of its administrative centre (where the weather is read).
PROVINCES = [
    ("01", "Hà Nội", 21.0285, 105.8542),
    ("04", "Cao Bằng", 22.6657, 106.2570),
    ("08", "Tuyên Quang", 21.8236, 105.2180),
    ("11", "Điện Biên", 21.3860, 103.0230),
    ("12", "Lai Châu", 22.3964, 103.4580),
    ("14", "Sơn La", 21.3270, 103.9141),
    ("15", "Lào Cai", 21.7229, 104.9113),
    ("19", "Thái Nguyên", 21.5942, 105.8482),
    ("20", "Lạng Sơn", 21.8537, 106.7610),
    ("22", "Quảng Ninh", 20.9590, 107.0448),
    ("24", "Bắc Ninh", 21.2731, 106.1946),
    ("25", "Phú Thọ", 21.3227, 105.4019),
    ("31", "Hải Phòng", 20.8449, 106.6881),
    ("33", "Hưng Yên", 20.6464, 106.0511),
    ("37", "Ninh Bình", 20.2506, 105.9745),
    ("38", "Thanh Hóa", 19.8067, 105.7852),
    ("40", "Nghệ An", 18.6796, 105.6813),
    ("42", "Hà Tĩnh", 18.3428, 105.9057),
    ("44", "Quảng Trị", 17.4689, 106.6223),
    ("46", "Huế", 16.4637, 107.5909),
    ("48", "Đà Nẵng", 16.0544, 108.2022),
    ("51", "Quảng Ngãi", 15.1214, 108.8044),
    ("52", "Gia Lai", 13.7830, 109.2197),
    ("56", "Khánh Hòa", 12.2388, 109.1967),
    ("66", "Đắk Lắk", 12.6667, 108.0500),
    ("68", "Lâm Đồng", 11.9404, 108.4583),
    ("75", "Đồng Nai", 10.9574, 106.8427),
    ("79", "Hồ Chí Minh", 10.7769, 106.7009),
    ("80", "Tây Ninh", 10.5359, 106.4137),
    ("82", "Đồng Tháp", 10.3600, 106.3600),
    ("86", "Vĩnh Long", 10.2537, 105.9722),
    ("91", "An Giang", 10.0125, 105.0809),
    ("92", "Cần Thơ", 10.0452, 105.7469),
    ("96", "Cà Mau", 9.1769, 105.1524),
]


def upgrade() -> None:
    province = op.create_table(
        "cat_province",
        sa.Column("code", sa.String(16), primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("lat", sa.Numeric(8, 5), nullable=False),
        sa.Column("lon", sa.Numeric(8, 5), nullable=False),
        schema="public",
    )
    op.bulk_insert(
        province, [{"code": c, "name": n, "lat": la, "lon": lo} for c, n, la, lo in PROVINCES]
    )
    # Free-text codes from before the catalog cannot be mapped: dropped rather than guessed.
    op.execute(
        "UPDATE public.tb_home SET province_code = NULL "
        "WHERE province_code NOT IN (SELECT code FROM public.cat_province)"
    )
    op.create_foreign_key(
        "fk_tb_home_province_code_cat_province",
        "tb_home",
        "cat_province",
        ["province_code"],
        ["code"],
        source_schema="public",
        referent_schema="public",
        onupdate="CASCADE",
        ondelete="SET NULL",
    )

    op.create_table(
        "tb_user_preference",
        sa.Column(
            "user_id",
            sa.Uuid,
            sa.ForeignKey("public.tb_users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("notify_anomaly", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("notify_tier", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("weekly_summary", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        schema="public",
    )

    # Detectors upsert on (home, dedup_key) while an alert is not resolved. Alerts are detector
    # output and the old kinds are no longer valid: dropped, the insight worker raises them again.
    op.execute("DELETE FROM public.tb_alert")
    op.add_column("tb_alert", sa.Column("dedup_key", sa.Text, nullable=False), schema="public")
    op.add_column(
        "tb_alert", sa.Column("resolved_at", sa.DateTime(timezone=True)), schema="public"
    )
    op.add_column(
        "tb_alert", sa.Column("notified_at", sa.DateTime(timezone=True)), schema="public"
    )
    op.create_check_constraint(
        op.f("ck_tb_alert_kind"),
        "tb_alert",
        "kind IN (" + ", ".join(f"'{k}'" for k in ALERT_KINDS) + ")",
        schema="public",
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_tb_alert_home_dedup_unresolved ON public.tb_alert "
        "(home_id, dedup_key) WHERE status <> 'resolved'"
    )

    op.create_table(
        "tb_notification_log",
        sa.Column("id", sa.Uuid, primary_key=True, server_default=sa.text("uuidv7()")),
        sa.Column(
            "user_id",
            sa.Uuid,
            sa.ForeignKey("public.tb_users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("ref", sa.Text, nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.UniqueConstraint("user_id", "kind", "ref", name="uq_tb_notification_log_user_kind_ref"),
        schema="public",
    )

    op.add_column(
        "ai_conversation",
        sa.Column("pinned", sa.Boolean, nullable=False, server_default=sa.false()),
        schema="ai",
    )
    op.add_column(
        "ai_conversation",
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        schema="ai",
    )
    op.create_index(
        "ix_ai_conversation_user_updated", "ai_conversation", ["user_id", "updated_at"], schema="ai"
    )
    op.add_column("ai_message", sa.Column("reply", sa.dialects.postgresql.JSONB), schema="ai")
    op.add_column("ai_message", sa.Column("feedback", sa.String(8)), schema="ai")
    op.create_check_constraint(
        op.f("ck_ai_message_feedback"), "ai_message", "feedback IN ('up', 'down')", schema="ai"
    )

    op.execute(f"GRANT SELECT ON public.cat_province TO {APP}, {COPILOT}")
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON public.tb_user_preference, "
        f"public.tb_notification_log TO {APP}"
    )


def downgrade() -> None:
    op.execute(f"REVOKE ALL ON public.tb_user_preference, public.tb_notification_log FROM {APP}")
    op.execute(f"REVOKE ALL ON public.cat_province FROM {APP}, {COPILOT}")
    op.drop_constraint(op.f("ck_ai_message_feedback"), "ai_message", schema="ai")
    op.drop_column("ai_message", "feedback", schema="ai")
    op.drop_column("ai_message", "reply", schema="ai")
    op.drop_index("ix_ai_conversation_user_updated", "ai_conversation", schema="ai")
    op.drop_column("ai_conversation", "updated_at", schema="ai")
    op.drop_column("ai_conversation", "pinned", schema="ai")
    op.drop_table("tb_notification_log", schema="public")
    op.execute("DROP INDEX public.uq_tb_alert_home_dedup_unresolved")
    op.drop_constraint(op.f("ck_tb_alert_kind"), "tb_alert", schema="public")
    op.drop_column("tb_alert", "notified_at", schema="public")
    op.drop_column("tb_alert", "resolved_at", schema="public")
    op.drop_column("tb_alert", "dedup_key", schema="public")
    op.drop_table("tb_user_preference", schema="public")
    op.drop_constraint("fk_tb_home_province_code_cat_province", "tb_home", schema="public")
    op.drop_table("cat_province", schema="public")
