from typing import Any

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.common.base_model import Base, IdMixin


class DeviceAlertRule(IdMixin, Base):
    __tablename__ = "tb_device_alert_rule"
    __table_args__ = (
        CheckConstraint("kind IN ('on','off','custom')", name="kind"),
        {"schema": "public"},
    )

    device_id: Mapped[int] = mapped_column(
        ForeignKey("public.tb_device.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(16))
    params: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    enabled: Mapped[bool] = mapped_column(default=True, server_default=text("true"))
