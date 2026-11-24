import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.common.base_model import NOW, Base, IdMixin

PLAN_KEYS = (
    "fewer_runs",
    "kettle_fill",
    "fridge_check",
    "heater_setpoint",
    "heater_earlier_off",
    "always_on",
)


class SavingsPlan(IdMixin, Base):
    """A person's savings plan for one billing cycle. `days` maps a local date to the frozen
    expected kWh (model `model_version`) and the meter's kWh over that day's measured hours."""

    __tablename__ = "tb_savings_plan"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'stopped')", name="status"),
        CheckConstraint("start_on <= end_on", name="span"),
        Index(
            "ux_tb_savings_plan_active",
            "home_id",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        {"schema": "public"},
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("public.tb_users.id", ondelete="CASCADE"))
    home_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("public.tb_home.id", ondelete="CASCADE"))
    start_on: Mapped[date] = mapped_column(Date)
    end_on: Mapped[date] = mapped_column(Date)
    model_version: Mapped[str] = mapped_column(Text)
    # The model's out-of-sample daily error (kWh): its spread, and its mean added to each day.
    sigma: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    bias: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=0, server_default="0")
    forecast_kwh: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    actions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    days: Mapped[dict[str, dict[str, float]]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    status: Mapped[str] = mapped_column(String(16), default="active", server_default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=NOW)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
