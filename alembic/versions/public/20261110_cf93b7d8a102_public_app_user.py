"""create the public-schema application user

Revision ID: cf93b7d8a102
Revises: b58a2d71c409
"""

import os

from alembic import context, op

revision = "cf93b7d8a102"
down_revision = "b58a2d71c409"
branch_labels = None
depends_on = None

ROLE = "wattprint_app"


def upgrade() -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{ROLE}') THEN
                CREATE ROLE {ROLE} NOLOGIN;
            END IF;
        END
        $$
        """
    )

    password = os.environ.get("APP_DB_PASSWORD", "")
    if password and context.is_offline_mode():
        raise RuntimeError("APP_DB_PASSWORD is set: refusing to write it into offline SQL")
    if password:
        escaped = password.replace("'", "''")
        op.execute(f"ALTER ROLE {ROLE} WITH LOGIN PASSWORD '{escaped}'")

    op.execute(
        f"DO $$ BEGIN EXECUTE format('GRANT CONNECT ON DATABASE %I TO {ROLE}', "
        "current_database()); END $$"
    )
    # Object grants come from the privilege matrix (4d7b1e9a3c52): least privilege, no ALL.


def downgrade() -> None:
    op.execute(
        f"DO $$ BEGIN EXECUTE format('REVOKE CONNECT ON DATABASE %I FROM {ROLE}', "
        "current_database()); END $$"
    )
