from app.common.base_repository import BaseRepository

from ..models import User


class UserRepository(BaseRepository[User]):
    model = User

    async def read_by_keycloak_sub(self, keycloak_sub: str) -> User | None:
        return await self.read_one(keycloak_sub=keycloak_sub)
