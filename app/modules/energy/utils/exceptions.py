from app.common.exceptions import NotFoundError, ServiceUnavailableError


class DeviceNotFoundError(NotFoundError):
    code = "device_not_found"
    message = "No such device in this home"


class HomeLocationUnsetError(NotFoundError):
    code = "home_location_unset"
    message = "The home has no province: set one to see its weather"


class WeatherUnavailableError(ServiceUnavailableError):
    code = "weather_unavailable"
    message = "Weather is unavailable right now"
