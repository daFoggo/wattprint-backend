"""old alerts get random ids (a UUIDv7 id tells its creation time), new ones too by default

Revision ID: a4f9c2e7b318
Revises: 3b6e9d2a7f15
"""

from alembic import op

revision = "a4f9c2e7b318"
down_revision = "3b6e9d2a7f15"
branch_labels = None
depends_on = None

FKS = (
    ("tb_suggestion", "fk_tb_suggestion_alert_id_tb_alert", "SET NULL"),
    ("tb_alert_feedback", "fk_tb_alert_feedback_alert_id_tb_alert", "CASCADE"),
)


def _fks(on_update: str) -> None:
    for table, name, on_delete in FKS:
        op.execute(
            f"ALTER TABLE public.{table} DROP CONSTRAINT {name}, ADD CONSTRAINT {name} "
            f"FOREIGN KEY (alert_id) REFERENCES public.tb_alert(id) "
            f"ON DELETE {on_delete}{on_update}"
        )


def upgrade() -> None:
    op.execute("ALTER TABLE public.tb_alert ALTER COLUMN id SET DEFAULT gen_random_uuid()")
    # One-off: the referencing rows follow through ON UPDATE CASCADE, then the keys are as before.
    _fks(" ON UPDATE CASCADE")
    op.execute(
        "CREATE TEMP TABLE alert_new_id ON COMMIT DROP AS "
        "SELECT id AS old, gen_random_uuid() AS new FROM public.tb_alert "
        "WHERE uuid_extract_version(id) = 7"
    )
    op.execute("UPDATE public.tb_alert a SET id = m.new FROM alert_new_id m WHERE a.id = m.old")
    # Mails sent before the per-day key logged the alert id as their ref.
    op.execute(
        "UPDATE public.tb_notification_log n SET ref = m.new::text FROM alert_new_id m "
        "WHERE n.kind = 'alert' AND n.ref = m.old::text"
    )
    op.execute("DROP TABLE alert_new_id")
    _fks("")


def downgrade() -> None:
    # The old ids are gone on purpose; only the default goes back.
    op.execute("ALTER TABLE public.tb_alert ALTER COLUMN id SET DEFAULT uuidv7()")
