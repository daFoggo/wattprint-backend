import uuid
from datetime import datetime

from sqlalchemy import (
    REAL,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.common.base_model import Base


class DeviceCycle(Base):
    """One on/off cycle of a device. Hypertable on start_ts (30-day chunks)."""

    __tablename__ = "tb_device_cycle"
    __table_args__ = (
        CheckConstraint("end_ts > start_ts", name="range"),
        Index("ix_device_cycle_home_start", "home_id", text("start_ts DESC")),
        {"schema": "public"},
    )

    home_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("public.tb_home.id", ondelete="CASCADE"))
    device_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("public.tb_device.id", ondelete="CASCADE"), primary_key=True
    )
    start_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    end_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    energy_wh: Mapped[float] = mapped_column(Float)
    peak_w: Mapped[float] = mapped_column(REAL)
