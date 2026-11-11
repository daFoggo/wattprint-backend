from app.common.base_repository import BaseRepository

from ..models import Bill


class BillRepository(BaseRepository[Bill]):
    model = Bill
