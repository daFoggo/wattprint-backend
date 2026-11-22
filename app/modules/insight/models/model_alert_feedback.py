import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.common.base_model import Base


class AlertFeedback(Base):
    """A member's verdict on an alert: "not_anomaly" widens the home's band for that kind."""

    __tablename__ = "tb_alert_feedback"
    __table_args__ = (
        CheckConstraint("verdict IN ('useful', 'not_anomaly')", name="verdict"),
        Index("ix_tb_alert_feedback_home_kind", "home_id", "kind", "at"),
        {"schema": "public"},
    )

    alert_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("public.tb_alert.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("public.tb_users.id", ondelete="CASCADE"), primary_key=True
    )
    home_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("public.tb_home.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(Text)
    verdict: Mapped[str] = mapped_column(Text)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
