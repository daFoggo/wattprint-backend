from pydantic import BaseModel, ConfigDict


class Preferences(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    notify_anomaly: bool = True
    notify_tier: bool = True
    weekly_summary: bool = False


class PreferencesUpdate(BaseModel):
    """Fields left out are kept."""

    model_config = ConfigDict(extra="forbid")

    notify_anomaly: bool | None = None
    notify_tier: bool | None = None
    weekly_summary: bool | None = None
