class AppError(Exception):
    """Base for every error that reaches the client through JDK's one
    standard error envelope (docs/modules/api_error_handling.md #1/#6).
    Route/service code should never raise a raw fastapi.HTTPException --
    always one of this class's subclasses, so an HTTP status and a
    machine-readable `code` are always coupled and deterministic per
    failure type (docs/audit/API_ERROR_HANDLING_AUDIT.md)."""

    code: str = "SERVER_ERROR"
    status_code: int = 500
    default_message: str = "Something went wrong. Please try again."

    def __init__(self, message: str | None = None, *, fields: dict[str, str] | None = None):
        message = message or self.default_message
        super().__init__(message)
        self.message = message
        self.fields = fields


class ValidationError(AppError):
    code = "VALIDATION_ERROR"
    status_code = 422
    default_message = "Please check your input and try again."


class AuthError(AppError):
    """Any authentication failure -- wrong credentials, invalid/expired
    token, locked-out account is NOT this (see RateLimitedError)."""

    code = "AUTHENTICATION_ERROR"
    status_code = 401
    default_message = "Invalid credentials."


class AccessDeniedError(AppError):
    code = "ACCESS_DENIED"
    status_code = 403
    default_message = "You do not have permission to do this."


class NotFoundError(AppError):
    code = "NOT_FOUND"
    status_code = 404
    default_message = "The requested record could not be found."


class ConflictError(AppError):
    code = "CONFLICT"
    status_code = 409
    default_message = "This action conflicts with existing data."


class BusinessRuleError(AppError):
    code = "BUSINESS_RULE_ERROR"
    status_code = 400
    default_message = "This action isn't allowed right now."


class RateLimitedError(AppError):
    code = "RATE_LIMITED"
    status_code = 429
    default_message = "Too many attempts. Please try again later."
