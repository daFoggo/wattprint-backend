from app.common.exceptions import (
    AppError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    UnprocessableError,
)


class HomeNotFoundError(NotFoundError):
    code = "home_not_found"
    message = "This account is not a member of any home"


class HomeOwnerRequiredError(ForbiddenError):
    code = "home_owner_required"
    message = "Only the home's owner can change it"


class DemoHomeReadOnlyError(ForbiddenError):
    code = "demo_home_read_only"
    message = "A demo home's data is public and cannot be erased"


class HomeReadOnlyError(ForbiddenError):
    code = "home_read_only"
    message = "This demo home is read-only"


class DetailRestrictedError(ForbiddenError):
    code = "detail_restricted"
    message = "The home's owner lets you see days only"


class GuestCannotJoinError(ForbiddenError):
    code = "guest_cannot_join"
    message = "A demo guest account is temporary: sign in with your own to join a home"


class InviteInvalidError(NotFoundError):
    code = "invite_invalid"
    message = "This code is wrong, used or out of date"


class AlreadyHasHomeError(ConflictError):
    code = "already_has_home"
    message = "This account already belongs to a home"


class MemberNotFoundError(NotFoundError):
    code = "member_not_found"
    message = "No such member in this home"


class InviteRateLimitedError(AppError):
    status_code = 429
    code = "invite_rate_limited"
    message = "Too many tries, wait a quarter of an hour"


class UnknownProvinceError(UnprocessableError):
    code = "unknown_province"
    message = "No such province"
