from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.common.base_model import NOW, BaseModel


class Device(BaseModel):
    __tablename__ = "tb_device"
    __table_args__ = (
        CheckConstraint("origin IN ('nilm','plug','manual')", name="origin"),
        CheckConstraint("active_to IS NULL OR active_to > active_from", name="validity_range"),
        {"schema": "public"},
    )

    home_id: Mapped[int] = mapped_column(
        ForeignKey("public.tb_home.id", ondelete="CASCADE"), index=True
    )
    device_type_code: Mapped[str] = mapped_column(ForeignKey("public.cat_device_type.code"))
    name: Mapped[str] = mapped_column(String(255))
    room: Mapped[str | None] = mapped_column(String(128))
    origin: Mapped[str] = mapped_column(String(16))
    show_on_timeline: Mapped[bool] = mapped_column(default=True, server_default=text("true"))
    active_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=NOW)
    active_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    merged_into_id: Mapped[int | None] = mapped_column(
        ForeignKey("public.tb_device.id"), index=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
