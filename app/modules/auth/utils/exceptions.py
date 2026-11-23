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


class DemoHomeNotFoundError(NotFoundError):
    code = "demo_home_not_found"
    message = "No such demo home"


class DemoUnavailableError(ServiceUnavailableError):
    code = "demo_unavailable"
    message = "Demo sign-in unavailable"


class DemoForbiddenError(ForbiddenError):
    code = "demo_forbidden"
    message = "Demo sign-in goes through the dashboard"


class DemoRateLimitedError(AppError):
    status_code = 429
    code = "demo_rate_limited"
    message = "Too many demo sign-ins in a minute; try again shortly"
