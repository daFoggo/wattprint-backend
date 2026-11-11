from app.common.base_repository import BaseRepository

from ..models import Alert


class AlertRepository(BaseRepository[Alert]):
    model = Alert
