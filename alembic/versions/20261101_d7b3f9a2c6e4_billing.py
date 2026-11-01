"""billing tables and vn_residential tariff seed

Revision ID: d7b3f9a2c6e4
Revises: c8a4e1f7b295
"""

from datetime import date

import sqlalchemy as sa

from alembic import op

revision = "d7b3f9a2c6e4"
down_revision = "c8a4e1f7b295"
branch_labels = None
depends_on = None

_VAT_NOTE = (
    "VAT 8% per the 2025-2026 VAT reduction; not confirmed from an official text for "
    "electricity - verify before 2027."
)

# plan code, valid_from, valid_to, vat_rate, source_doc, tiers (from, to, price before VAT)
VERSIONS = [
    (
        date(2025, 5, 10), date(2026, 10, 31), "0.0800",
        "Decision 1279/QD-BCT; prices supplied by the project owner. " + _VAT_NOTE,
        [(0, 50, 1984), (50, 100, 2050), (100, 200, 2380), (200, 300, 2998),
         (300, 400, 3350), (400, None, 3460)],
    ),
    (
        date(2026, 11, 1), None, "0.0800",
        "Decision 2892; prices supplied by the project owner, cross-checked against a "
        "Thanh Nien report dated 2026-11-01. " + _VAT_NOTE,
        [(0, 100, 1901), (100, 200, 2289), (200, 400, 2894), (400, 700, 3456),
         (700, None, 3844)],
    ),
]
PLAN = "vn_residential"


def _seed() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "INSERT INTO billing.tariff_plan (code, name, currency) "
            "VALUES (:c, 'Vietnam residential electricity', 'VND') ON CONFLICT (code) DO NOTHING"
        ),
        {"c": PLAN},
    )
    for valid_from, valid_to, vat, doc, tiers in VERSIONS:
        conn.execute(
            sa.text(
                "INSERT INTO billing.tariff_version "
                "(plan_code, valid_from, valid_to, vat_rate, source_doc) "
                "VALUES (:p, :f, :t, :v, :d) "
                "ON CONFLICT (plan_code, valid_from) DO NOTHING"
            ),
            {"p": PLAN, "f": valid_from, "t": valid_to, "v": vat, "d": doc},
        )
        vid = conn.scalar(
            sa.text(
                "SELECT id FROM billing.tariff_version "
                "WHERE plan_code = :p AND valid_from = :f"
            ),
            {"p": PLAN, "f": valid_from},
        )
        for no, (lo, hi, price) in enumerate(tiers, start=1):
            conn.execute(
                sa.text(
                    "INSERT INTO billing.tariff_tier "
                    "(version_id, tier_no, from_kwh, to_kwh, price_per_kwh) "
                    "VALUES (:v, :n, :lo, :hi, :pr) ON CONFLICT (version_id, tier_no) DO NOTHING"
                ),
                {"v": vid, "n": no, "lo": lo, "hi": hi, "pr": price},
            )


def upgrade() -> None:
    uuid_pk = sa.text("gen_random_uuid()")
    op.create_table(
        "tariff_plan",
        sa.Column("code", sa.String(64), primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("currency", sa.Text, nullable=False, server_default="VND"),
        schema="billing",
    )
    op.create_table(
        "tariff_version",
        sa.Column("id", sa.UUID, primary_key=True, server_default=uuid_pk),
        sa.Column("plan_code", sa.String(64), nullable=False),
        sa.Column("valid_from", sa.Date, nullable=False),
        sa.Column("valid_to", sa.Date),
        sa.Column("vat_rate", sa.Numeric(5, 4), nullable=False),
        sa.Column("source_doc", sa.Text, nullable=False),
        sa.ForeignKeyConstraint(["plan_code"], ["billing.tariff_plan.code"]),
        sa.CheckConstraint("valid_to IS NULL OR valid_to >= valid_from", name="validity_range"),
        sa.UniqueConstraint("plan_code", "valid_from"),
        schema="billing",
    )
    op.create_index("ix_tariff_version_plan_code", "tariff_version", ["plan_code"],
                    schema="billing")
    op.create_table(
        "tariff_tier",
        sa.Column("version_id", sa.UUID, nullable=False),
        sa.Column("tier_no", sa.SmallInteger, nullable=False),
        sa.Column("from_kwh", sa.Numeric(10, 2), nullable=False),
        sa.Column("to_kwh", sa.Numeric(10, 2)),
        sa.Column("price_per_kwh", sa.Numeric(12, 2), nullable=False),
        sa.PrimaryKeyConstraint("version_id", "tier_no"),
        sa.ForeignKeyConstraint(["version_id"], ["billing.tariff_version.id"], ondelete="CASCADE"),
        sa.CheckConstraint("to_kwh IS NULL OR to_kwh > from_kwh", name="range"),
        schema="billing",
    )
    op.create_table(
        "bill",
        sa.Column("id", sa.UUID, primary_key=True, server_default=uuid_pk),
        sa.Column("home_id", sa.UUID, nullable=False),
        sa.Column("period_start", sa.Date, nullable=False),
        sa.Column("period_end", sa.Date, nullable=False),
        sa.Column("version_id", sa.UUID, nullable=False),
        sa.Column("kwh_total", sa.Numeric(12, 3), nullable=False),
        sa.Column("amount_before_vat", sa.Numeric(14, 2), nullable=False),
        sa.Column("vat_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("amount_total", sa.Numeric(14, 2), nullable=False),
        sa.Column("coverage", sa.Numeric(5, 4), nullable=False),
        sa.Column("tariff_straddle", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["home_id"], ["core.home.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["version_id"], ["billing.tariff_version.id"]),
        sa.CheckConstraint("status IN ('open','partial','closed')", name="status"),
        sa.UniqueConstraint("home_id", "period_start"),
        schema="billing",
    )
    op.create_index("ix_bill_home_id", "bill", ["home_id"], schema="billing")
    op.create_index("ix_bill_version_id", "bill", ["version_id"], schema="billing")
    op.create_table(
        "bill_item",
        sa.Column("id", sa.UUID, primary_key=True, server_default=uuid_pk),
        sa.Column("bill_id", sa.UUID, nullable=False),
        sa.Column("device_id", sa.UUID),
        sa.Column("label", sa.Text, nullable=False),
        sa.Column("kwh", sa.Numeric(12, 3), nullable=False),
        sa.Column("share", sa.Numeric(7, 6), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.ForeignKeyConstraint(["bill_id"], ["billing.bill.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["device_id"], ["core.device.id"], ondelete="SET NULL"),
        schema="billing",
    )
    op.create_index("ix_bill_item_bill_id", "bill_item", ["bill_id"], schema="billing")
    op.create_index("ix_bill_item_device_id", "bill_item", ["device_id"], schema="billing")

    _seed()
    op.create_foreign_key(
        "fk_home_tariff_plan_code_tariff_plan", "home", "tariff_plan",
        ["tariff_plan_code"], ["code"], source_schema="core", referent_schema="billing",
        onupdate="CASCADE", ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_home_tariff_plan_code_tariff_plan", "home", schema="core",
                       type_="foreignkey")
    for table in ("bill_item", "bill", "tariff_tier", "tariff_version", "tariff_plan"):
        op.drop_table(table, schema="billing")
