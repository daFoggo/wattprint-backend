import uuid
from datetime import datetime

from sqlalchemy import (
    ARRAY,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.common.base_model import NOW, Base

# Written through app.common.outbound and auth.services.consent (plain SQL); declared here so the
# schema, its indexes included, matches the migration.


class ConsentRecord(Base):
    """Append-only: the app role may only insert and read."""

    __tablename__ = "tb_consent"
    __table_args__ = (
        CheckConstraint("purpose IN ('wappi','voice','email')", name="purpose"),
        Index("ix_tb_consent_user_purpose_created", "user_id", "purpose", text("created_at DESC")),
        {"schema": "public"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid7, server_default=text("uuidv7()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("public.tb_users.id", ondelete="CASCADE"))
    purpose: Mapped[str] = mapped_column(String(16))
    granted: Mapped[bool]
    version: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=NOW)


class OutboundLog(Base):
    __tablename__ = "tb_outbound_log"
    __table_args__ = (
        Index("ix_tb_outbound_log_user_created", "user_id", "created_at"),
        Index("ix_tb_outbound_log_home_created", "home_id", "created_at"),
        Index("ix_tb_outbound_log_created", "created_at"),
        {"schema": "public"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid7, server_default=text("uuidv7()")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=NOW)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("public.tb_users.id", ondelete="CASCADE")
    )
    home_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("public.tb_home.id", ondelete="CASCADE")
    )
    party: Mapped[str] = mapped_column(String(32))
    purpose: Mapped[str] = mapped_column(String(32))
    data: Mapped[list[str]] = mapped_column(ARRAY(Text))
    detail: Mapped[str | None] = mapped_column(String(16))
