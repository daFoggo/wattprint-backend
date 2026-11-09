import uuid

from pydantic import BaseModel, ConfigDict


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str  # Keycloak is the validator of record
    full_name: str | None
    is_active: bool


class Me(UserRead):
    roles: list[str]
