from sqlalchemy import String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.common.base_model import BaseModel


# Local profile of a Keycloak user. The external subject is stored separately from the local ID.
class User(BaseModel):
    __tablename__ = "tb_users"
    __table_args__ = {"schema": "public"}

    keycloak_sub: Mapped[str | None] = mapped_column(String(255), unique=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    full_name: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(default=True, server_default=text("true"))
