from app.common.base_repository import BaseRepository

from ..models import ForecastSnapshot


class ForecastSnapshotRepository(BaseRepository[ForecastSnapshot]):
    model = ForecastSnapshot
