from sqlalchemy import (
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.common.base_model import Base


class DeviceType(Base):
    __tablename__ = "cat_device_type"
    __table_args__ = {"schema": "public"}

    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    label_vi: Mapped[str] = mapped_column(String(128))
    label_en: Mapped[str] = mapped_column(String(128))
    typical_watts: Mapped[int | None] = mapped_column(Integer)
    tip_text: Mapped[str | None] = mapped_column(Text)
