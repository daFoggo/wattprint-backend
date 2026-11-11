from app.common.base_repository import BaseRepository

from ..models import CohortStat


class CohortStatRepository(BaseRepository[CohortStat]):
    model = CohortStat
