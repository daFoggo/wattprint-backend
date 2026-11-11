from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.common.base_model import Base, IdMixin


class Alert(IdMixin, Base):
    __tablename__ = "tb_alert"
    __table_args__ = (
        CheckConstraint("severity IN ('info','warning','critical')", name="severity"),
        CheckConstraint("status IN ('open','acknowledged','resolved')", name="status"),
        Index("ix_alert_home_ts", "home_id", text("ts DESC")),
        {"schema": "public"},
    )

    home_id: Mapped[int] = mapped_column(ForeignKey("public.tb_home.id", ondelete="CASCADE"))
    device_id: Mapped[int | None] = mapped_column(
        ForeignKey("public.tb_device.id", ondelete="SET NULL"), index=True
    )
    kind: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(16))
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    status: Mapped[str] = mapped_column(String(16), default="open", server_default="open")
