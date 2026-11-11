from app.common.base_repository import BaseRepository

from ..models import Home


class HomeRepository(BaseRepository[Home]):
    model = Home
