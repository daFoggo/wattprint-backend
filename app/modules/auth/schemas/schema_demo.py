from pydantic import BaseModel


class DemoDevice(BaseModel):
    label: str  # NILM label (Fridge, WashMach, ...): what the drawing picks its shape by
    name: str  # the appliance's REFIT name in that house


class DemoHome(BaseModel):
    key: str
    house: int
    name: str
    devices: list[DemoDevice]
