"""enable timescaledb

Revision ID: a1c3f5b7d9e2
Revises: e8d6cdf24fe4
"""

from alembic import op

revision = "a1c3f5b7d9e2"
down_revision = "e8d6cdf24fe4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")


def downgrade() -> None:
    pass
