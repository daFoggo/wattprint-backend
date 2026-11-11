from app.common.base_repository import BaseRepository

from ..models import Series


class SeriesRepository(BaseRepository[Series]):
    model = Series
