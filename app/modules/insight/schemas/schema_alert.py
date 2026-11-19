import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class AlertDevice(BaseModel):
    id: uuid.UUID
    name: str
    type: str  # cat_device_type.code, for its icon


class AlertRead(BaseModel):
    """What a detector found; the text comes from `kind` and the figures in `payload`."""

    id: uuid.UUID
    kind: str
    severity: str
    status: str
    ts: datetime
    resolved_at: datetime | None
    device: AlertDevice | None
    payload: dict[str, float]


class AlertUpdate(BaseModel):
    """Seen: the alert leaves the Overview. Resolving is the detector's, when the cause is gone."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["acknowledged"]
