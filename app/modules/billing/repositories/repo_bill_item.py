from app.common.base_repository import BaseRepository

from ..models import BillItem


class BillItemRepository(BaseRepository[BillItem]):
    model = BillItem
