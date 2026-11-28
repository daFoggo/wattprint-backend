"""how fine each member of a home may see its use

Revision ID: c4d8a1f6b2e9
Revises: 9d2b6f3a1c58
"""

import sqlalchemy as sa

from alembic import op

revision = "c4d8a1f6b2e9"
down_revision = "9d2b6f3a1c58"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Rows already there keep what they see today; an accepted invite writes 'daily'.
    op.add_column(
        "tb_home_member",
        sa.Column("detail", sa.String(8), nullable=False, server_default="full"),
        schema="public",
    )
    op.create_check_constraint(
        "detail", "tb_home_member", "detail IN ('full','daily')", schema="public"
    )


def downgrade() -> None:
    op.drop_column("tb_home_member", "detail", schema="public")
