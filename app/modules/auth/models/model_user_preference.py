import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, true
from sqlalchemy.orm import Mapped, mapped_column

from app.common.base_model import NOW, Base, utcnow


class UserPreference(Base):
    __tablename__ = "tb_user_preference"
    __table_args__ = {"schema": "public"}

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("public.tb_users.id", ondelete="CASCADE"), primary_key=True
    )
    notify_anomaly: Mapped[bool] = mapped_column(default=True, server_default=true())
    notify_tier: Mapped[bool] = mapped_column(default=True, server_default=true())
    weekly_summary: Mapped[bool] = mapped_column(default=False, server_default="false")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, server_default=NOW
    )
