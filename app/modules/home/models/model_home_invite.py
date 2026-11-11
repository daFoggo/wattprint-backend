import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.common.base_model import Base, IdMixin


class HomeInvite(IdMixin, Base):
    __tablename__ = "tb_home_invite"
    __table_args__ = (
        CheckConstraint("role IN ('owner','member')", name="role"),
        {"schema": "public"},
    )

    home_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("public.tb_home.id", ondelete="CASCADE"), index=True
    )
    code_hash: Mapped[str] = mapped_column(String(128), unique=True)
    role: Mapped[str] = mapped_column(String(16), default="member", server_default="member")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("public.tb_users.id"), index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
