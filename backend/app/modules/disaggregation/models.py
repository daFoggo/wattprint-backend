from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, func
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
class ApplianceTruth(Base):
    __tablename__ = "appliance_truth"

    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    house_id: Mapped[int] = mapped_column(ForeignKey("houses.id"), primary_key=True)
    appliance: Mapped[str] = mapped_column(String(50), primary_key=True)
    watts: Mapped[float] = mapped_column(Float)
class SimulationJob(Base):
    __tablename__ = "simulation_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    house_id: Mapped[int] = mapped_column(ForeignKey("houses.id"), index=True)
    owner_id: Mapped[str] = mapped_column(String)
    day: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|running|done|failed
    rows_per_second: Mapped[float] = mapped_column(Float)
    total_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    done_minutes: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)