from app.common.exceptions import (
    AppError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ServiceUnavailableError,
    UnauthorizedError,
)


class InvalidCredentialsError(UnauthorizedError):
    code = "invalid_credentials"
    message = "Could not validate credentials"

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message, headers={"WWW-Authenticate": "Bearer"})


class IdentityProviderUnavailableError(ServiceUnavailableError):
    code = "identity_provider_unavailable"
    message = "Identity provider unreachable"


class EmailTakenError(ConflictError):
    code = "email_taken"
    message = "Email belongs to another account"


class InactiveUserError(ForbiddenError):
    code = "inactive_user"
    message = "Inactive user"


class AdminRequiredError(ForbiddenError):
    code = "admin_required"
    message = "Admin role required"


class HomeHasMembersError(ConflictError):
    code = "home_has_members"
    message = "Other people belong to this home; their data is not yours to erase"


class AccountDeleteUnavailableError(ServiceUnavailableError):
    code = "account_delete_unavailable"
    message = "The account could not be deleted right now; try again shortly"


class DemoHomeNotFoundError(NotFoundError):
    code = "demo_home_not_found"
    message = "No such demo home"


class DemoNotForMembersError(ConflictError):
    code = "demo_not_for_members"
    message = "This account belongs to a home; demo homes are for accounts without one"


class DemoForbiddenError(ForbiddenError):
    code = "demo_forbidden"
    message = "Demo guests are made through the dashboard"


class DemoUnavailableError(ServiceUnavailableError):
    code = "demo_unavailable"
    message = "Demo guests unavailable"


class DemoFullError(ServiceUnavailableError):
    code = "demo_full"
    message = "Too many demo guests right now; try again later"


class DemoRateLimitedError(AppError):
    status_code = 429
    code = "demo_rate_limited"
    message = "Too many demo guests in a minute; try again shortly"
