from app.common.exceptions import NotFoundError


class HomeNotFoundError(NotFoundError):
    code = "home_not_found"
    message = "This account is not a member of any home"


class DeviceNotFoundError(NotFoundError):
    code = "device_not_found"
    message = "No such device in this home"
