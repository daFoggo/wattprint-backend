"""tb_home_member role viewer: a demo visitor's read-only view of a demo home

Revision ID: a4b8d0f6e235
Revises: f3a7c9e5d124
"""

from alembic import op

revision = "a4b8d0f6e235"
down_revision = "f3a7c9e5d124"
branch_labels = None
depends_on = None

NAME = "ck_tb_home_member_ck_home_member_role"  # as the first revision named it


def _roles(*roles: str) -> None:
    op.execute(f"ALTER TABLE public.tb_home_member DROP CONSTRAINT {NAME}")
    op.execute(
        f"ALTER TABLE public.tb_home_member ADD CONSTRAINT {NAME} CHECK (role IN ("
        + ", ".join(f"'{r}'" for r in roles)
        + "))"
    )


def upgrade() -> None:
    _roles("owner", "member", "viewer")


def downgrade() -> None:
    op.execute("DELETE FROM public.tb_home_member WHERE role = 'viewer'")
    _roles("owner", "member")
