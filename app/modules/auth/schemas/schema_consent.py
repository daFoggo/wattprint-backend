from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

Purpose = Literal["wappi", "voice", "email"]


class Consent(BaseModel):
    purpose: Purpose
    granted: bool  # on the current wording; an older yes counts as no
    version: str | None  # the wording last answered
    at: datetime | None
    current_version: str


class ConsentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    granted: bool


class OutboundRow(BaseModel):
    created_at: datetime
    party: str
    purpose: str
    data: list[str]
    detail: str | None
