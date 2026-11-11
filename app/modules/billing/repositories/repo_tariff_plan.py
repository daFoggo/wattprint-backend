from app.common.base_repository import BaseRepository

from ..models import TariffPlan


class TariffPlanRepository(BaseRepository[TariffPlan]):
    model = TariffPlan
