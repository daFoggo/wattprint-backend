"""foundation: extensions, schemas, roles

Revision ID: b2d4f6a8c0e1
Revises: a1c3f5b7d9e2
"""

import os

from alembic import context, op

revision = "b2d4f6a8c0e1"
down_revision = "a1c3f5b7d9e2"
branch_labels = None
depends_on = None

EXTENSIONS = ("timescaledb", "vector", "unaccent", "pg_trgm")
SCHEMAS = ("core", "catalog", "energy", "billing", "insight", "copilot", "knowledge", "ops")
# role name -> env var holding its password
ROLES = {
    "wattprint_app": "APP_DB_PASSWORD",
    "wattprint_ingest": "INGEST_DB_PASSWORD",
    "wattprint_copilot_ro": "COPILOT_DB_PASSWORD",
}


def ensure_role(execute, name: str, password: str) -> None:
    """Create the role if missing (NOLOGIN); with a password, (re)set LOGIN PASSWORD.

    Roles are cluster-wide. Without a password an existing role keeps its login state and
    password: a re-run never demotes it. `execute` takes one SQL string.
    """
    execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{name}') THEN
                CREATE ROLE {name} NOLOGIN;
            END IF;
        END
        $$
        """
    )
    if password:
        escaped = password.replace("'", "''")
        execute(f"ALTER ROLE {name} WITH LOGIN PASSWORD '{escaped}'")


def upgrade() -> None:
    for ext in EXTENSIONS:
        op.execute(f"CREATE EXTENSION IF NOT EXISTS {ext}")
    for schema in SCHEMAS:
        op.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
    for name, env_var in ROLES.items():
        password = os.environ.get(env_var, "")
        if password and context.is_offline_mode():
            raise RuntimeError(f"{env_var} is set: refusing to write a password into offline SQL")
        ensure_role(op.execute, name, password)
    op.execute("ALTER ROLE wattprint_copilot_ro SET statement_timeout = '5s'")


def downgrade() -> None:
    # Extensions and cluster-wide roles (attributes, passwords) are never touched. Only this
    # database's grants are revoked and the schemas this revision created are dropped; DROP
    # SCHEMA without CASCADE fails if a later revision left objects in one.
    for schema in reversed(SCHEMAS):
        for name in ROLES:
            op.execute(f"REVOKE ALL ON SCHEMA {schema} FROM {name}")
        op.execute(f"DROP SCHEMA IF EXISTS {schema}")
