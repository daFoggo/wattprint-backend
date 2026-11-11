from app.common.base_repository import BaseRepository

from ..models import IngestCheckpoint


class IngestCheckpointRepository(BaseRepository[IngestCheckpoint]):
    model = IngestCheckpoint
