from app.common.base_repository import BaseRepository

from ..models import TariffVersion


class TariffVersionRepository(BaseRepository[TariffVersion]):
    model = TariffVersion
