"""initial billing module: tariff and bill tables

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
        date(2025, 5, 10),
        date(2026, 10, 31),
        "0.0800",
        "Decision 1279/QD-BCT; prices supplied by the project owner. " + _VAT_NOTE,
        [
            (0, 50, 1984),
            (50, 100, 2050),
            (100, 200, 2380),
            (200, 300, 2998),
            (300, 400, 3350),
            (400, None, 3460),
        ],
    ),
    (
        date(2026, 11, 1),
        None,
        "0.0800",
        "Decision 2892; prices supplied by the project owner, cross-checked against a "
        "Thanh Nien report dated 2026-11-01. " + _VAT_NOTE,
        [(0, 100, 1901), (100, 200, 2289), (200, 400, 2894), (400, 700, 3456), (700, None, 3844)],
    ),
]
PLAN = "vn_residential"


def _seed() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "INSERT INTO public.tb_tariff_plan (code, name, currency) "
            "VALUES (:c, 'Vietnam residential electricity', 'VND') ON CONFLICT (code) DO NOTHING"
        ),
        {"c": PLAN},
    )
    for valid_from, valid_to, vat, doc, tiers in VERSIONS:
        conn.execute(
            sa.text(
                "INSERT INTO public.tb_tariff_version "
                "(plan_code, valid_from, valid_to, vat_rate, source_doc) "
                "VALUES (:p, :f, :t, :v, :d) "
                "ON CONFLICT (plan_code, valid_from) DO NOTHING"
            ),
            {"p": PLAN, "f": valid_from, "t": valid_to, "v": vat, "d": doc},
        )
        vid = conn.scalar(
            sa.text(
                "SELECT id FROM public.tb_tariff_version WHERE plan_code = :p AND valid_from = :f"
            ),
            {"p": PLAN, "f": valid_from},
        )
        for no, (lo, hi, price) in enumerate(tiers, start=1):
            conn.execute(
                sa.text(
                    "INSERT INTO public.tb_tariff_tier "
                    "(version_id, tier_no, from_kwh, to_kwh, price_per_kwh) "
                    "VALUES (:v, :n, :lo, :hi, :pr) ON CONFLICT (version_id, tier_no) DO NOTHING"
                ),
                {"v": vid, "n": no, "lo": lo, "hi": hi, "pr": price},
            )


def upgrade() -> None:
    op.create_table(
        "tb_tariff_plan",
        sa.Column("code", sa.String(64), primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("currency", sa.Text, nullable=False, server_default="VND"),
        schema="public",
    )
    op.create_table(
        "tb_tariff_version",
        sa.Column("id", sa.Integer, sa.Identity(always=False), primary_key=True),
        sa.Column("plan_code", sa.String(64), nullable=False),
        sa.Column("valid_from", sa.Date, nullable=False),
        sa.Column("valid_to", sa.Date),
        sa.Column("vat_rate", sa.Numeric(5, 4), nullable=False),
        sa.Column("source_doc", sa.Text, nullable=False),
        sa.ForeignKeyConstraint(["plan_code"], ["public.tb_tariff_plan.code"]),
        sa.CheckConstraint("valid_to IS NULL OR valid_to >= valid_from", name="validity_range"),
        sa.UniqueConstraint("plan_code", "valid_from"),
        schema="public",
    )
    op.create_table(
        "tb_tariff_tier",
        sa.Column("version_id", sa.Integer, nullable=False),
        sa.Column("tier_no", sa.SmallInteger, nullable=False),
        sa.Column("from_kwh", sa.Numeric(10, 2), nullable=False),
        sa.Column("to_kwh", sa.Numeric(10, 2)),
        sa.Column("price_per_kwh", sa.Numeric(12, 2), nullable=False),
        sa.PrimaryKeyConstraint("version_id", "tier_no"),
        sa.ForeignKeyConstraint(
            ["version_id"], ["public.tb_tariff_version.id"], ondelete="CASCADE"
        ),
        sa.CheckConstraint("to_kwh IS NULL OR to_kwh > from_kwh", name="range"),
        schema="public",
    )
    op.create_table(
        "tb_bill",
        sa.Column("id", sa.Integer, sa.Identity(always=False), primary_key=True),
        sa.Column("home_id", sa.Integer, nullable=False),
        sa.Column("period_start", sa.Date, nullable=False),
        sa.Column("period_end", sa.Date, nullable=False),
        sa.Column("version_id", sa.Integer, nullable=False),
        sa.Column("kwh_total", sa.Numeric(12, 3), nullable=False),
        sa.Column("amount_before_vat", sa.Numeric(14, 2), nullable=False),
        sa.Column("vat_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("amount_total", sa.Numeric(14, 2), nullable=False),
        sa.Column("coverage", sa.Numeric(5, 4), nullable=False),
        sa.Column("tariff_straddle", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["home_id"], ["public.tb_home.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["version_id"], ["public.tb_tariff_version.id"]),
        sa.CheckConstraint("status IN ('open','partial','closed')", name="status"),
        sa.UniqueConstraint("home_id", "period_start"),
        schema="public",
    )
    op.create_table(
        "tb_bill_item",
        sa.Column("id", sa.Integer, sa.Identity(always=False), primary_key=True),
        sa.Column("bill_id", sa.Integer, nullable=False),
        sa.Column("device_id", sa.Integer),
        sa.Column("label", sa.Text, nullable=False),
        sa.Column("kwh", sa.Numeric(12, 3), nullable=False),
        sa.Column("share", sa.Numeric(7, 6), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.ForeignKeyConstraint(["bill_id"], ["public.tb_bill.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["device_id"], ["public.tb_device.id"], ondelete="SET NULL"),
        schema="public",
    )

    _seed()
    op.create_foreign_key(
        "fk_home_tariff_plan_code_tariff_plan",
        "tb_home",
        "tb_tariff_plan",
        ["tariff_plan_code"],
        ["code"],
        source_schema="public",
        referent_schema="public",
        onupdate="CASCADE",
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_home_tariff_plan_code_tariff_plan", "tb_home", schema="public", type_="foreignkey"
    )
    for table in (
        "tb_bill_item",
        "tb_bill",
        "tb_tariff_tier",
        "tb_tariff_version",
        "tb_tariff_plan",
    ):
        op.drop_table(table, schema="public")
