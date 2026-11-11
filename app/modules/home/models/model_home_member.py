import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.common.base_model import NOW, Base


class HomeMember(Base):
    __tablename__ = "tb_home_member"
    __table_args__ = (
        CheckConstraint("role IN ('owner','member')", name="role"),
        UniqueConstraint("user_id"),  # one account, one home
        {"schema": "public"},
    )

    home_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("public.tb_home.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("public.tb_users.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(16), default="member", server_default="member")
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=NOW)
