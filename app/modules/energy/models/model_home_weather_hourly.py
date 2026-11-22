import uuid
from datetime import datetime

from sqlalchemy import REAL, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.common.base_model import Base


class HomeWeatherHourly(Base):
    __tablename__ = "tb_home_weather_hourly"
    __table_args__ = {"schema": "public"}

    home_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("public.tb_home.id", ondelete="CASCADE"), primary_key=True
    )
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    temp_c: Mapped[float | None] = mapped_column(REAL)
    humidity_pct: Mapped[float | None] = mapped_column(REAL)
    apparent_c: Mapped[float | None] = mapped_column(REAL)
    cloud_pct: Mapped[float | None] = mapped_column(REAL)
    radiation_wm2: Mapped[float | None] = mapped_column(REAL)
    precip_mm: Mapped[float | None] = mapped_column(REAL)
    is_day: Mapped[bool | None] = mapped_column(Boolean)
    wind_ms: Mapped[float | None] = mapped_column(REAL)
