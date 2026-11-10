"""initialize public schema and enable TimescaleDB

Revision ID: b58a2d71c409
Revises:
"""

from alembic import op

revision = "b58a2d71c409"
down_revision = None
branch_labels = ("public",)
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS public")
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")


def downgrade() -> None:
    # The public schema is built in, and the extension is shared by later migrations.
    pass
