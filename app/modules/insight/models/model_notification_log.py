import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.common.base_model import NOW, Base, IdMixin, utcnow


class NotificationLog(IdMixin, Base):
    """One row per mail sent, so a job re-run never mails the same thing twice."""

    __tablename__ = "tb_notification_log"
    __table_args__ = (
        UniqueConstraint("user_id", "kind", "ref", name="uq_tb_notification_log_user_kind_ref"),
        {"schema": "public"},
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("public.tb_users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(32))
    ref: Mapped[str] = mapped_column(Text)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=NOW
    )
