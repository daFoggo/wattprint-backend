from app.common.base_repository import BaseRepository

from ..models import DeviceCycle


class DeviceCycleRepository(BaseRepository[DeviceCycle]):
    model = DeviceCycle
