from app.common.exceptions import (
    ConflictError,
    ForbiddenError,
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
