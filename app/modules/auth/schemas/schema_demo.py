from pydantic import BaseModel, Field


class DemoDevice(BaseModel):
    label: str  # NILM label (Fridge, WashMach, ...): what the drawing picks its shape by
    name: str  # the appliance's REFIT name in that house


class DemoHome(BaseModel):
    key: str
    house: int
    name: str
    devices: list[DemoDevice]


class DemoSessionIn(BaseModel):
    house: str = Field(min_length=1, max_length=32)


class DemoTokens(BaseModel):
    access_token: str
    refresh_token: str
    id_token: str
    expires_in: int
    refresh_expires_in: int
