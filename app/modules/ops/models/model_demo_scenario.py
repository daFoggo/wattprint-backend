import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.common.base_model import Base, IdMixin

SCENARIOS = ("heater", "forgotten_load", "base_up", "away", "cold_spell")


class DemoScenario(IdMixin, Base):
    __tablename__ = "tb_demo_scenario"
    __table_args__ = (
        CheckConstraint(f"name IN ({', '.join(repr(n) for n in SCENARIOS)})", name="name"),
        CheckConstraint("ends_at IS NULL OR ends_at > starts_at", name="window"),
        Index("ix_tb_demo_scenario_home", "home_id", "starts_at"),
        {"schema": "public"},
    )

    home_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("public.tb_home.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(Text)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    params: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    train: Mapped[bool] = mapped_column(Boolean)
