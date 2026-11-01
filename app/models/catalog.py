from sqlalchemy import CheckConstraint, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class Metric(Base):
    __tablename__ = "metric"
    __table_args__ = (
        CheckConstraint("aggregation IN ('mean','max','energy')", name="aggregation"),
        {"schema": "catalog"},
    )

    event_type: Mapped[str] = mapped_column(String(64), primary_key=True)
    unit: Mapped[str] = mapped_column(String(16))
    aggregation: Mapped[str] = mapped_column(String(16))


class DeviceType(Base):
    __tablename__ = "device_type"
    __table_args__ = {"schema": "catalog"}

    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    label_vi: Mapped[str] = mapped_column(String(128))
    label_en: Mapped[str] = mapped_column(String(128))
    typical_watts: Mapped[int | None] = mapped_column(Integer)
    tip_text: Mapped[str | None] = mapped_column(Text)
