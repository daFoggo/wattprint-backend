from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class House(Base):
    __tablename__ = "houses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)  # = REFIT house id
    owner_id: Mapped[str] = mapped_column(String, index=True)  # Better Auth user id (JWT sub), no FK
    name: Mapped[str] = mapped_column(String(100))
    step_sec: Mapped[int] = mapped_column(Integer, server_default="60")


class AggregatePower(Base):
    __tablename__ = "aggregate_power"

    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    house_id: Mapped[int] = mapped_column(ForeignKey("houses.id"), primary_key=True)
    watts: Mapped[float] = mapped_column(Float)


class AppliancePower(Base):
    __tablename__ = "appliance_power"

    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    house_id: Mapped[int] = mapped_column(ForeignKey("houses.id"), primary_key=True)
    appliance: Mapped[str] = mapped_column(String(50), primary_key=True)
    watts: Mapped[float] = mapped_column(Float)