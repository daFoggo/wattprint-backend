from datetime import UTC, datetime

from sqlalchemy import DateTime, Identity, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


# Local profile of a Keycloak user. The external subject is stored separately from the local ID.
class User(Base):
    __tablename__ = "tb_users"
    __table_args__ = {"schema": "public"}

    id: Mapped[int] = mapped_column(Integer, Identity(always=False), primary_key=True)
    keycloak_sub: Mapped[str | None] = mapped_column(String(255), unique=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    full_name: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(default=True, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), server_default=text("now()")
    )
