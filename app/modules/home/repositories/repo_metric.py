from app.common.base_repository import BaseRepository

from ..models import Metric


class MetricRepository(BaseRepository[Metric]):
    model = Metric
