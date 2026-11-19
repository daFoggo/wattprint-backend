from pydantic import BaseModel, ConfigDict


class _Model(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Sky(_Model):
    description: str
    icon: str


class WeatherNow(_Model):
    dt: int
    temp: float
    feels_like: float
    humidity: int
    wind_speed: float
    sky: Sky


class WeatherSlot(_Model):
    dt: int
    temp: float
    pop: float
    sky: Sky


class Weather(_Model):
    province: str
    now: WeatherNow
    next: list[WeatherSlot]
