"""tb_tariff_version.doc_code: the short code of the decision behind each version's prices.

Revision ID: e2c6a8d4b917
Revises: d9a4e6b2c751
"""

from datetime import date

import sqlalchemy as sa

from alembic import op

revision = "e2c6a8d4b917"
down_revision = "d9a4e6b2c751"
branch_labels = None
depends_on = None

CODES = {date(2025, 5, 10): "QĐ 1279/QĐ-BCT", date(2026, 11, 1): "QĐ 2892/QĐ-BCT"}


def upgrade() -> None:
    op.add_column("tb_tariff_version", sa.Column("doc_code", sa.Text), schema="public")
    for valid_from, code in CODES.items():
        op.execute(
            sa.text(
                "UPDATE public.tb_tariff_version SET doc_code = :c "
                "WHERE plan_code = 'vn_residential' AND valid_from = :f"
            ).bindparams(c=code, f=valid_from)
        )


def downgrade() -> None:
    op.drop_column("tb_tariff_version", "doc_code", schema="public")
