from datetime import datetime

from sqlalchemy import (
    REAL,
    DateTime,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.common.base_model import Base


class WeatherHourly(Base):
    __tablename__ = "tb_weather_hourly"
    __table_args__ = {"schema": "public"}

    province_code: Mapped[str] = mapped_column(Text, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    temp_c: Mapped[float | None] = mapped_column(REAL)
    humidity_pct: Mapped[float | None] = mapped_column(REAL)
