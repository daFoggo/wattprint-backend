from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base

_NOW = text("now()")


class TariffPlan(Base):
    __tablename__ = "tb_tariff_plan"
    __table_args__ = {"schema": "public"}

    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    currency: Mapped[str] = mapped_column(Text, default="VND", server_default="VND")


class TariffVersion(Base):
    __tablename__ = "tb_tariff_version"
    __table_args__ = (
        CheckConstraint("valid_to IS NULL OR valid_to >= valid_from", name="validity_range"),
        UniqueConstraint("plan_code", "valid_from"),
        {"schema": "public"},
    )

    id: Mapped[int] = mapped_column(Integer, Identity(always=False), primary_key=True)
    plan_code: Mapped[str] = mapped_column(
        String(64), ForeignKey("public.tb_tariff_plan.code"), index=True
    )
    valid_from: Mapped[date] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    vat_rate: Mapped[Decimal] = mapped_column(Numeric(5, 4))
    source_doc: Mapped[str] = mapped_column(Text)


class TariffTier(Base):
    """A tier covers kWh in the interval (from_kwh, to_kwh]; the last tier has to_kwh NULL."""

    __tablename__ = "tb_tariff_tier"
    __table_args__ = (
        CheckConstraint("to_kwh IS NULL OR to_kwh > from_kwh", name="range"),
        {"schema": "public"},
    )

    version_id: Mapped[int] = mapped_column(
        ForeignKey("public.tb_tariff_version.id", ondelete="CASCADE"), primary_key=True
    )
    tier_no: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    from_kwh: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    to_kwh: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    price_per_kwh: Mapped[Decimal] = mapped_column(Numeric(12, 2))


class Bill(Base):
    __tablename__ = "tb_bill"
    __table_args__ = (
        CheckConstraint("status IN ('open','partial','closed')", name="status"),
        UniqueConstraint("home_id", "period_start"),
        {"schema": "public"},
    )

    id: Mapped[int] = mapped_column(Integer, Identity(always=False), primary_key=True)
    home_id: Mapped[int] = mapped_column(
        ForeignKey("public.tb_home.id", ondelete="CASCADE"), index=True
    )
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    version_id: Mapped[int] = mapped_column(ForeignKey("public.tb_tariff_version.id"), index=True)
    kwh_total: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    amount_before_vat: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    vat_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    amount_total: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    coverage: Mapped[Decimal] = mapped_column(Numeric(5, 4))
    tariff_straddle: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    status: Mapped[str] = mapped_column(String(16))
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)


class BillItem(Base):
    __tablename__ = "tb_bill_item"
    __table_args__ = {"schema": "public"}

    id: Mapped[int] = mapped_column(Integer, Identity(always=False), primary_key=True)
    bill_id: Mapped[int] = mapped_column(
        ForeignKey("public.tb_bill.id", ondelete="CASCADE"), index=True
    )
    device_id: Mapped[int | None] = mapped_column(
        ForeignKey("public.tb_device.id", ondelete="SET NULL"), index=True
    )
    label: Mapped[str] = mapped_column(Text)
    kwh: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    share: Mapped[Decimal] = mapped_column(Numeric(7, 6))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
