"""initialize AI schema, role and login user

Revision ID: 8c2f6a1d4b90
Revises: 37d2a9f40c61
"""

import os

from alembic import context, op

revision = "8c2f6a1d4b90"
down_revision = "37d2a9f40c61"
branch_labels = None
depends_on = None

ROLE = "wattprint_ai"
USER = "wattprint_ai_user"


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS ai")
    op.execute("REVOKE ALL ON SCHEMA ai FROM PUBLIC")

    op.execute(
        f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{ROLE}') "
        f"THEN CREATE ROLE {ROLE} NOLOGIN; END IF; END $$"
    )
    op.execute(
        f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{USER}') "
        f"THEN CREATE ROLE {USER} NOLOGIN; END IF; END $$"
    )

    password = os.environ.get("AI_DB_PASSWORD", "")
    if password and context.is_offline_mode():
        raise RuntimeError("AI_DB_PASSWORD is set: refusing to write it into offline SQL")
    if password:
        escaped = password.replace("'", "''")
        op.execute(f"ALTER ROLE {USER} WITH LOGIN PASSWORD '{escaped}'")

    op.execute(f"GRANT {ROLE} TO {USER}")
    op.execute(
        f"DO $$ BEGIN EXECUTE format('GRANT CONNECT ON DATABASE %I TO {ROLE}', "
        "current_database()); END $$"
    )
    op.execute(f"GRANT USAGE ON SCHEMA ai TO {ROLE}")
    op.execute(f"ALTER ROLE {USER} SET search_path = ai, pg_catalog")
    op.execute(f"ALTER ROLE {USER} SET statement_timeout = '30s'")


def downgrade() -> None:
    op.execute(f"ALTER ROLE {USER} RESET statement_timeout")
    op.execute(f"ALTER ROLE {USER} RESET search_path")
    op.execute(f"REVOKE USAGE ON SCHEMA ai FROM {ROLE}")
    op.execute(
        f"DO $$ BEGIN EXECUTE format('REVOKE CONNECT ON DATABASE %I FROM {ROLE}', "
        "current_database()); END $$"
    )
    op.execute(f"REVOKE {ROLE} FROM {USER}")
    op.execute("DROP SCHEMA IF EXISTS ai")
