"""cat_device_type: the rice cooker, a device of the ENERTALK (Korea) demo home.

Revision ID: d9a4e6b2c751
Revises: c7e2f4a9b158
"""

from alembic import op

revision = "d9a4e6b2c751"
down_revision = "c7e2f4a9b158"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "INSERT INTO public.cat_device_type (code, label_vi, label_en, typical_watts, tip_text) "
        "VALUES ('rice_cooker', 'Nồi cơm điện', 'Rice cooker', 700, "
        "'Cook only what you need; unplug it once the rice is done instead of keeping it warm.') "
        "ON CONFLICT (code) DO NOTHING"
    )


def downgrade() -> None:
    op.execute("DELETE FROM public.cat_device_type WHERE code = 'rice_cooker'")
