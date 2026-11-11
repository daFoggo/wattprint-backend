from app.common.base_repository import BaseRepository

from ..models import Device


class DeviceRepository(BaseRepository[Device]):
    model = Device
