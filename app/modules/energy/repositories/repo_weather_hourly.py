from app.common.base_repository import BaseRepository

from ..models import WeatherHourly


class WeatherHourlyRepository(BaseRepository[WeatherHourly]):
    model = WeatherHourly
