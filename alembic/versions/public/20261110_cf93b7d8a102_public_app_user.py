"""create the public-schema application user and grants

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
    op.execute(f"GRANT ALL PRIVILEGES ON SCHEMA public TO {ROLE}")
    op.execute(
        f"""
        DO $$
        DECLARE obj record;
        BEGIN
            FOR obj IN
                SELECT c.relname, c.relkind
                FROM pg_class AS c
                JOIN pg_namespace AS n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public'
                  AND c.relname <> 'alembic_version'
                  AND c.relkind IN ('r', 'p', 'v', 'm', 'f', 'S')
            LOOP
                IF obj.relkind = 'S' THEN
                    EXECUTE format(
                        'GRANT ALL PRIVILEGES ON SEQUENCE %I.%I TO {ROLE}',
                        'public', obj.relname
                    );
                ELSE
                    EXECUTE format(
                        'GRANT ALL PRIVILEGES ON TABLE %I.%I TO {ROLE}',
                        'public', obj.relname
                    );
                END IF;
            END LOOP;
        END
        $$
        """
    )
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL PRIVILEGES ON TABLES TO {ROLE}"
    )
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL PRIVILEGES ON SEQUENCES TO {ROLE}"
    )
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL PRIVILEGES ON FUNCTIONS TO {ROLE}"
    )
    op.execute(f"GRANT ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA public TO {ROLE}")


def downgrade() -> None:
    op.execute(
        f"""
        DO $$
        DECLARE obj record;
        BEGIN
            FOR obj IN
                SELECT c.relname, c.relkind
                FROM pg_class AS c
                JOIN pg_namespace AS n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public'
                  AND c.relname <> 'alembic_version'
                  AND c.relkind IN ('r', 'p', 'v', 'm', 'f', 'S')
            LOOP
                IF obj.relkind = 'S' THEN
                    EXECUTE format(
                        'REVOKE ALL PRIVILEGES ON SEQUENCE %I.%I FROM {ROLE}',
                        'public', obj.relname
                    );
                ELSE
                    EXECUTE format(
                        'REVOKE ALL PRIVILEGES ON TABLE %I.%I FROM {ROLE}',
                        'public', obj.relname
                    );
                END IF;
            END LOOP;
        END
        $$
        """
    )
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL PRIVILEGES ON FUNCTIONS FROM {ROLE}"
    )
    op.execute(f"REVOKE ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA public FROM {ROLE}")
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL PRIVILEGES ON SEQUENCES FROM {ROLE}"
    )
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL PRIVILEGES ON TABLES FROM {ROLE}"
    )
    op.execute(f"REVOKE ALL PRIVILEGES ON SCHEMA public FROM {ROLE}")
    op.execute(
        f"DO $$ BEGIN EXECUTE format('REVOKE CONNECT ON DATABASE %I FROM {ROLE}', "
        "current_database()); END $$"
    )
