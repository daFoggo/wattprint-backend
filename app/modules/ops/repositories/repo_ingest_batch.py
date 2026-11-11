from app.common.base_repository import BaseRepository

from ..models import IngestBatch


class IngestBatchRepository(BaseRepository[IngestBatch]):
    model = IngestBatch
