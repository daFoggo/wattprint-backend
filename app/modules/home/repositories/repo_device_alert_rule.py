from app.common.base_repository import BaseRepository

from ..models import DeviceAlertRule


class DeviceAlertRuleRepository(BaseRepository[DeviceAlertRule]):
    model = DeviceAlertRule
