from app.common.base_repository import BaseRepository

from ..models import DeviceType


class DeviceTypeRepository(BaseRepository[DeviceType]):
    model = DeviceType
