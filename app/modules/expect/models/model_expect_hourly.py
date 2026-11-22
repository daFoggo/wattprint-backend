import uuid
from datetime import datetime

from sqlalchemy import REAL, DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.common.base_model import Base


class ExpectHourly(Base):
    __tablename__ = "tb_expect_hourly"
    __table_args__ = {"schema": "public"}

    home_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("public.tb_home.id", ondelete="CASCADE"), primary_key=True
    )
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    p05: Mapped[float] = mapped_column(REAL)
    p10: Mapped[float] = mapped_column(REAL)
    p50: Mapped[float] = mapped_column(REAL)
    p90: Mapped[float] = mapped_column(REAL)
    p95: Mapped[float] = mapped_column(REAL)
    c_weather: Mapped[float] = mapped_column(REAL)
    c_calendar: Mapped[float] = mapped_column(REAL)
    c_occupancy: Mapped[float] = mapped_column(REAL)
    c_trend: Mapped[float] = mapped_column(REAL)
    c_base: Mapped[float] = mapped_column(REAL)
    model_version: Mapped[str] = mapped_column(Text)
