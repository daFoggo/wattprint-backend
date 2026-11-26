"""tb_tariff_version: the 2027 version at 10% VAT.

Revision ID: f4b8c2e6a913
Revises: e2c6a8d4b917

Nghị quyết 204/2025/QH15 (Điều 2) cuts VAT to 8% from 2025-07-01 to the end of 2026-12-31; the VAT
law (Điều 9 khoản 3) sets 10% after. No decision extending the cut existed on 2026-11-26. The
prices are the QĐ 2892/QĐ-BCT prices carried forward. If the cut is extended, or EVN changes the
prices, add a revision that moves this version's start or replaces it.
"""

from datetime import date

import sqlalchemy as sa

from alembic import op

revision = "f4b8c2e6a913"
down_revision = "e2c6a8d4b917"
branch_labels = None
depends_on = None

PLAN = "vn_residential"
NOTE = (
    "QĐ 2892/QĐ-BCT prices carried forward; VAT 10% because Resolution 204/2025/QH15 (8%) ends "
    "2026-12-31 (Art. 2) and VAT Law Art. 9(3) sets 10%. No extension known on 2026-11-26: "
    "verify before 2027."
)


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE public.tb_tariff_version SET valid_to = :t "
            "WHERE plan_code = :p AND valid_from = :f AND valid_to IS NULL"
        ),
        {"t": date(2026, 12, 31), "p": PLAN, "f": date(2026, 11, 1)},
    )
    conn.execute(
        sa.text(
            "INSERT INTO public.tb_tariff_version "
            "(plan_code, valid_from, valid_to, vat_rate, source_doc, doc_code) "
            "VALUES (:p, :f, NULL, 0.10, :d, 'QĐ 2892/QĐ-BCT')"
        ),
        {"p": PLAN, "f": date(2027, 1, 1), "d": NOTE},
    )
    conn.execute(
        sa.text(
            "INSERT INTO public.tb_tariff_tier "
            "(version_id, tier_no, from_kwh, to_kwh, price_per_kwh) "
            "SELECT n.id, t.tier_no, t.from_kwh, t.to_kwh, t.price_per_kwh "
            "FROM public.tb_tariff_version o "
            "JOIN public.tb_tariff_tier t ON t.version_id = o.id "
            "JOIN public.tb_tariff_version n ON n.plan_code = o.plan_code AND n.valid_from = :n "
            "WHERE o.plan_code = :p AND o.valid_from = :f"
        ),
        {"p": PLAN, "f": date(2026, 11, 1), "n": date(2027, 1, 1)},
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text("DELETE FROM public.tb_tariff_version WHERE plan_code = :p AND valid_from = :f"),
        {"p": PLAN, "f": date(2027, 1, 1)},
    )
    conn.execute(
        sa.text(
            "UPDATE public.tb_tariff_version SET valid_to = NULL "
            "WHERE plan_code = :p AND valid_from = :f"
        ),
        {"p": PLAN, "f": date(2026, 11, 1)},
    )
