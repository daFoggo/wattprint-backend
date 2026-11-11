import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.common.base_model import Base, IdMixin


class Meter(IdMixin, Base):
    __tablename__ = "tb_meter"
    __table_args__ = (
        CheckConstraint("status IN ('new','active','retired')", name="status"),
        Index(
            "ix_meter_claim_code_hash",
            "claim_code_hash",
            unique=True,
            postgresql_where=text("claim_code_hash IS NOT NULL"),
        ),
        {"schema": "public"},
    )

    serial: Mapped[str] = mapped_column(String(64), unique=True)
    home_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("public.tb_home.id"), index=True)
    claim_code_hash: Mapped[str | None] = mapped_column(String(128))
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    firmware: Mapped[str | None] = mapped_column(String(64))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="new", server_default="new")
