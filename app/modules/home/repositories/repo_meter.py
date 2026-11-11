from app.common.base_repository import BaseRepository

from ..models import Meter


class MeterRepository(BaseRepository[Meter]):
    model = Meter
