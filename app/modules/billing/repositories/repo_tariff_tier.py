from app.common.base_repository import BaseRepository

from ..models import TariffTier


class TariffTierRepository(BaseRepository[TariffTier]):
    model = TariffTier
