"""server defaults for users and refresh_tokens

Revision ID: d4f6b8c0e2a1
Revises: c3e5a7b9d1f0
"""

import sqlalchemy as sa

from alembic import op

revision = "d4f6b8c0e2a1"
down_revision = "c3e5a7b9d1f0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("tb_users", "is_active", server_default=sa.text("true"))
    op.alter_column("tb_users", "created_at", server_default=sa.text("now()"))
    op.alter_column("tb_refresh_tokens", "created_at", server_default=sa.text("now()"))


def downgrade() -> None:
    op.alter_column("tb_refresh_tokens", "created_at", server_default=None)
    op.alter_column("tb_users", "created_at", server_default=None)
    op.alter_column("tb_users", "is_active", server_default=None)
