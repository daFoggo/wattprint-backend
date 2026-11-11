from app.common.base_repository import BaseRepository

from ..models import InferenceRun


class InferenceRunRepository(BaseRepository[InferenceRun]):
    model = InferenceRun
