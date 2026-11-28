from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Numeric,
    SmallInteger,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.common.base_model import BaseModel


class Home(BaseModel):
    __tablename__ = "tb_home"
    __table_args__ = (
        CheckConstraint("home_type IN ('apartment','house','other')", name="home_type"),
        CheckConstraint("billing_cycle_day BETWEEN 1 AND 28", name="billing_cycle_day"),
        CheckConstraint("timezone = 'Asia/Ho_Chi_Minh'", name="timezone"),
        CheckConstraint("ai_detail IN ('daily','hourly')", name="ai_detail"),
        {"schema": "public"},
    )

    name: Mapped[str] = mapped_column(String(255))
    postal_code: Mapped[str | None] = mapped_column(String(16))
    province_code: Mapped[str | None] = mapped_column(
        String(16), ForeignKey("public.cat_province.code", onupdate="CASCADE", ondelete="SET NULL")
    )
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
    # How fine the numbers Wappi sends out may be; NULL follows settings.copilot_ai_detail_default.
    ai_detail: Mapped[str | None] = mapped_column(String(8))
    # History before this moment was erased by the owner; a meter sending it again is refused.
    history_erased_before: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
