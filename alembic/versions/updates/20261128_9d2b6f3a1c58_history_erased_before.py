"""the day a home's history was erased up to, so a meter cannot send it again

Revision ID: 9d2b6f3a1c58
Revises: 8c1e47aa2d90
"""

import sqlalchemy as sa

from alembic import op

revision = "9d2b6f3a1c58"
down_revision = "8c1e47aa2d90"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tb_home",
        sa.Column("history_erased_before", sa.DateTime(timezone=True)),
        schema="public",
    )


def downgrade() -> None:
    op.drop_column("tb_home", "history_erased_before", schema="public")
