from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

HomeType = Literal["apartment", "house", "other"]


class Province(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    name: str


class HomeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    home_type: HomeType | None
    floor_area_m2: Decimal | None
    occupants: int | None
    billing_cycle_day: int
    province_code: str | None
    role: Literal["owner", "member"]


class HomeUpdate(BaseModel):
    """Fields left out are kept; null clears an optional one."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    home_type: HomeType | None = None
    floor_area_m2: Decimal | None = Field(default=None, gt=0, le=10_000, decimal_places=2)
    occupants: int | None = Field(default=None, ge=1, le=30)
    billing_cycle_day: int | None = Field(default=None, ge=1, le=28)
    province_code: str | None = Field(default=None, max_length=16)
