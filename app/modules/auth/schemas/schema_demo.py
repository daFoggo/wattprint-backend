from pydantic import BaseModel


class DemoDevice(BaseModel):
    label: str  # NILM label (Fridge, WashMach, ...): what the drawing picks its shape by
    name: str  # the appliance's REFIT name in that house


class DemoHome(BaseModel):
    key: str
    house: int
    name: str
    devices: list[DemoDevice]


class DemoTokens(BaseModel):
    """Keycloak tokens for a new guest, minted for the dashboard's client."""

    access_token: str
    refresh_token: str
    id_token: str
    expires_in: int
    refresh_expires_in: int
