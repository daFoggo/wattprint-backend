"""ingest reads a home's erase day, so a meter cannot send erased history again

Revision ID: 3b6e9d2a7f15
Revises: e7a3c91b5d40
"""

from alembic import op

revision = "3b6e9d2a7f15"
down_revision = "e7a3c91b5d40"
branch_labels = None
depends_on = None

GRANT = "SELECT (id, history_erased_before) ON public.tb_home"


def upgrade() -> None:
    op.execute(f"GRANT {GRANT} TO wattprint_ingest")


def downgrade() -> None:
    op.execute(f"REVOKE {GRANT} FROM wattprint_ingest")
