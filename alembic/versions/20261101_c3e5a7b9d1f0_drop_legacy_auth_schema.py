"""drop legacy auth schema

Revision ID: c3e5a7b9d1f0
Revises: a1c3f5b7d9e2
"""

from alembic import op

revision = "c3e5a7b9d1f0"
down_revision = "a1c3f5b7d9e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Leftover schema of the previous external auth service; the app no longer uses it.
    op.execute("DROP SCHEMA IF EXISTS auth CASCADE")


def downgrade() -> None:
    pass
