from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base

_NOW = text("now()")


class Home(Base):
    __tablename__ = "tb_home"
    __table_args__ = (
        CheckConstraint("home_type IN ('apartment','house','other')", name="home_type"),
        CheckConstraint("billing_cycle_day BETWEEN 1 AND 28", name="billing_cycle_day"),
        CheckConstraint("timezone = 'Asia/Ho_Chi_Minh'", name="timezone"),
        {"schema": "public"},
    )

    id: Mapped[int] = mapped_column(Integer, Identity(always=False), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    postal_code: Mapped[str | None] = mapped_column(String(16))
    province_code: Mapped[str | None] = mapped_column(String(16))
    home_type: Mapped[str | None] = mapped_column(String(16))
    floor_area_m2: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    year_built: Mapped[int | None] = mapped_column(SmallInteger)
    occupants: Mapped[int | None] = mapped_column(SmallInteger)
    timezone: Mapped[str] = mapped_column(
        String(64), default="Asia/Ho_Chi_Minh", server_default="Asia/Ho_Chi_Minh"
    )
    tariff_plan_code: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("public.tb_tariff_plan.code", onupdate="CASCADE", ondelete="SET NULL"),
    )
    billing_cycle_day: Mapped[int] = mapped_column(SmallInteger, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)


class HomeMember(Base):
    __tablename__ = "tb_home_member"
    __table_args__ = (
        CheckConstraint("role IN ('owner','member')", name="role"),
        UniqueConstraint("user_id"),  # one account, one home
        {"schema": "public"},
    )

    home_id: Mapped[int] = mapped_column(
        ForeignKey("public.tb_home.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("public.tb_users.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(16), default="member", server_default="member")
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)


class HomeInvite(Base):
    __tablename__ = "tb_home_invite"
    __table_args__ = (
        CheckConstraint("role IN ('owner','member')", name="role"),
        {"schema": "public"},
    )

    id: Mapped[int] = mapped_column(Integer, Identity(always=False), primary_key=True)
    home_id: Mapped[int] = mapped_column(
        ForeignKey("public.tb_home.id", ondelete="CASCADE"), index=True
    )
    code_hash: Mapped[str] = mapped_column(String(128), unique=True)
    role: Mapped[str] = mapped_column(String(16), default="member", server_default="member")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_by: Mapped[int | None] = mapped_column(ForeignKey("public.tb_users.id"), index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Meter(Base):
    __tablename__ = "tb_meter"
    __table_args__ = (
        CheckConstraint("status IN ('new','active','retired')", name="status"),
        Index(
            "ix_meter_claim_code_hash",
            "claim_code_hash",
            unique=True,
            postgresql_where=text("claim_code_hash IS NOT NULL"),
        ),
        {"schema": "public"},
    )

    id: Mapped[int] = mapped_column(Integer, Identity(always=False), primary_key=True)
    serial: Mapped[str] = mapped_column(String(64), unique=True)
    home_id: Mapped[int | None] = mapped_column(ForeignKey("public.tb_home.id"), index=True)
    claim_code_hash: Mapped[str | None] = mapped_column(String(128))
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    firmware: Mapped[str | None] = mapped_column(String(64))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="new", server_default="new")


class Device(Base):
    __tablename__ = "tb_device"
    __table_args__ = (
        CheckConstraint("origin IN ('nilm','plug','manual')", name="origin"),
        CheckConstraint("active_to IS NULL OR active_to > active_from", name="validity_range"),
        {"schema": "public"},
    )

    id: Mapped[int] = mapped_column(Integer, Identity(always=False), primary_key=True)
    home_id: Mapped[int] = mapped_column(
        ForeignKey("public.tb_home.id", ondelete="CASCADE"), index=True
    )
    device_type_code: Mapped[str] = mapped_column(ForeignKey("public.cat_device_type.code"))
    name: Mapped[str] = mapped_column(String(255))
    room: Mapped[str | None] = mapped_column(String(128))
    origin: Mapped[str] = mapped_column(String(16))
    show_on_timeline: Mapped[bool] = mapped_column(default=True, server_default=text("true"))
    active_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
    active_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    merged_into_id: Mapped[int | None] = mapped_column(
        ForeignKey("public.tb_device.id"), index=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)


class DeviceAlertRule(Base):
    __tablename__ = "tb_device_alert_rule"
    __table_args__ = (
        CheckConstraint("kind IN ('on','off','custom')", name="kind"),
        {"schema": "public"},
    )

    id: Mapped[int] = mapped_column(Integer, Identity(always=False), primary_key=True)
    device_id: Mapped[int] = mapped_column(
        ForeignKey("public.tb_device.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(16))
    params: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    enabled: Mapped[bool] = mapped_column(default=True, server_default=text("true"))
