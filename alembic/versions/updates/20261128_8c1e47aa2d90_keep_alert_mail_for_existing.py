"""accounts that never saved preferences keep their alert mail; only new accounts start off

Revision ID: 8c1e47aa2d90
Revises: 602f4f387869
"""

from alembic import op

revision = "8c1e47aa2d90"
down_revision = "602f4f387869"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Before 602f4f387869 a missing row meant "on": write that down for the accounts that had it.
    op.execute(
        "INSERT INTO public.tb_user_preference (user_id, notify_anomaly, notify_tier) "
        "SELECT u.id, true, true FROM public.tb_users u "
        "WHERE NOT EXISTS (SELECT 1 FROM public.tb_user_preference p WHERE p.user_id = u.id)"
    )


def downgrade() -> None:
    pass  # the rows say what the old defaults meant; nothing to undo
