from app.common.base_repository import BaseRepository

from ..models import Watch


class WatchRepository(BaseRepository[Watch]):
    model = Watch
