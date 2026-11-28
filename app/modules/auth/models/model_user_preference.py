import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, false
from sqlalchemy.orm import Mapped, mapped_column

from app.common.base_model import NOW, Base, utcnow


class UserPreference(Base):
    __tablename__ = "tb_user_preference"
    __table_args__ = {"schema": "public"}

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("public.tb_users.id", ondelete="CASCADE"), primary_key=True
    )
    # Off until chosen, like the email consent they also need (R3.3).
    notify_anomaly: Mapped[bool] = mapped_column(default=False, server_default=false())
    notify_tier: Mapped[bool] = mapped_column(default=False, server_default=false())
    weekly_summary: Mapped[bool] = mapped_column(default=False, server_default="false")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, server_default=NOW
    )
