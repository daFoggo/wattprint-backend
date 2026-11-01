import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base

_UUID_DEFAULT = text("gen_random_uuid()")
_NOW = text("now()")


class Home(Base):
    __tablename__ = "home"
    __table_args__ = (
        CheckConstraint("home_type IN ('apartment','house','other')", name="home_type"),
        CheckConstraint("billing_cycle_day BETWEEN 1 AND 28", name="billing_cycle_day"),
        CheckConstraint("timezone = 'Asia/Ho_Chi_Minh'", name="timezone"),
        {"schema": "core"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=_UUID_DEFAULT
    )
    name: Mapped[str] = mapped_column(String(255))
    postal_code: Mapped[str | None] = mapped_column(String(16))
    province_code: Mapped[str | None] = mapped_column(String(16))
    home_type: Mapped[str | None] = mapped_column(String(16))
    floor_area_m2: Mapped[float | None] = mapped_column(Numeric(8, 2))
    year_built: Mapped[int | None] = mapped_column(SmallInteger)
    occupants: Mapped[int | None] = mapped_column(SmallInteger)
    timezone: Mapped[str] = mapped_column(
        String(64), default="Asia/Ho_Chi_Minh", server_default="Asia/Ho_Chi_Minh"
    )
    # FK to billing.tariff_plan(code) is added with the billing tables.
    tariff_plan_code: Mapped[str | None] = mapped_column(String(64))
    billing_cycle_day: Mapped[int] = mapped_column(SmallInteger, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)


class HomeMember(Base):
    __tablename__ = "home_member"
    __table_args__ = (
        CheckConstraint("role IN ('owner','member')", name="role"),
        UniqueConstraint("user_id"),  # one account, one home
        {"schema": "core"},
    )

    home_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.home.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("public.users.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(16), default="member")
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)


class HomeInvite(Base):
    __tablename__ = "home_invite"
    __table_args__ = (
        CheckConstraint("role IN ('owner','member')", name="role"),
        {"schema": "core"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=_UUID_DEFAULT
    )
    home_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.home.id", ondelete="CASCADE"))
    code_hash: Mapped[str] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(16), default="member", server_default="member")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("public.users.id"))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Meter(Base):
    __tablename__ = "meter"
    __table_args__ = (
        CheckConstraint("status IN ('new','active','retired')", name="status"),
        {"schema": "core"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=_UUID_DEFAULT
    )
    serial: Mapped[str] = mapped_column(String(64), unique=True)
    home_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("core.home.id"))
    claim_code_hash: Mapped[str | None] = mapped_column(String(128))
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    firmware: Mapped[str | None] = mapped_column(String(64))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="new", server_default="new")


class Device(Base):
    __tablename__ = "device"
    __table_args__ = (
        CheckConstraint("origin IN ('nilm','plug','manual')", name="origin"),
        CheckConstraint("active_to IS NULL OR active_to > active_from", name="validity_range"),
        {"schema": "core"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=_UUID_DEFAULT
    )
    home_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.home.id", ondelete="CASCADE"))
    device_type_code: Mapped[str] = mapped_column(ForeignKey("catalog.device_type.code"))
    name: Mapped[str] = mapped_column(String(255))
    room: Mapped[str | None] = mapped_column(String(128))
    origin: Mapped[str] = mapped_column(String(16))
    show_on_timeline: Mapped[bool] = mapped_column(default=True, server_default=text("true"))
    active_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
    active_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("core.device.id"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)


class DeviceAlertRule(Base):
    __tablename__ = "device_alert_rule"
    __table_args__ = (
        CheckConstraint("kind IN ('on','off','custom')", name="kind"),
        {"schema": "core"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=_UUID_DEFAULT
    )
    device_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.device.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(16))
    params: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    enabled: Mapped[bool] = mapped_column(default=True, server_default=text("true"))
