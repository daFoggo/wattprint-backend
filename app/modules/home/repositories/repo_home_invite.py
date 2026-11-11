from app.common.base_repository import BaseRepository

from ..models import HomeInvite


class HomeInviteRepository(BaseRepository[HomeInvite]):
    model = HomeInvite
