from app.common.exceptions import ForbiddenError, NotFoundError, UnprocessableError


class HomeNotFoundError(NotFoundError):
    code = "home_not_found"
    message = "This account is not a member of any home"


class HomeOwnerRequiredError(ForbiddenError):
    code = "home_owner_required"
    message = "Only the home's owner can change it"


class UnknownProvinceError(UnprocessableError):
    code = "unknown_province"
    message = "No such province"
