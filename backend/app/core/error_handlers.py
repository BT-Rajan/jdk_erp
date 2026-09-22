import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.errors import AppError
from app.core.logging import get_logger, log
from app.core.request_context import get_request_id

# Routed through the one central logging setup
# (docs/modules/logging_request_tracing.md #1) -- app/core/logging.py's
# get_logger/configure_logging, not an ad-hoc handler of this module's
# own. jdk_clean's equivalent ("app") had no configured handler anywhere
# in its own repo (see docs/audit/API_ERROR_HANDLING_AUDIT.md).
logger = get_logger("errors")

_STATUS_TO_CODE = {
    status.HTTP_401_UNAUTHORIZED: "AUTHENTICATION_ERROR",
    status.HTTP_403_FORBIDDEN: "ACCESS_DENIED",
    status.HTTP_404_NOT_FOUND: "NOT_FOUND",
    status.HTTP_405_METHOD_NOT_ALLOWED: "METHOD_NOT_ALLOWED",
    status.HTTP_409_CONFLICT: "CONFLICT",
    status.HTTP_422_UNPROCESSABLE_CONTENT: "VALIDATION_ERROR",
    status.HTTP_429_TOO_MANY_REQUESTS: "RATE_LIMITED",
}


def _error_response(
    status_code: int, code: str, message: str, fields: dict[str, str] | None = None
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "success": False,
            "error": {"code": code, "message": message, "fields": fields},
            "request_id": get_request_id(),
        },
    )


def _log_error(request: Request, level: int, message: str, *, exc_info: bool = False, **fields) -> None:
    """Reads user_id/organisation_id from request.state, not the
    matching ContextVars -- FastAPI runs every sync dependency
    (app.api.deps.get_current_user) in a worker thread, so a mutation it
    makes to a ContextVar never propagates back to this handler's own
    context; request.state is a plain shared object, so it's the one
    thing that reliably crosses that boundary (docs/modules/logging_request_tracing.md #3,
    docs/audit/LOGGING_REQUEST_TRACING_AUDIT.md)."""
    log(
        logger,
        level,
        message,
        exc_info=exc_info,
        user_id=getattr(request.state, "user_id", None),
        organisation_id=getattr(request.state, "organisation_id", None),
        **fields,
    )


def register_exception_handlers(app: FastAPI) -> None:
    """One chokepoint for every failure shape
    (docs/modules/api_error_handling.md #1) -- no module registers its
    own error handling. Each handler also stamps request.state.error_code
    so RequestLoggingMiddleware's one-line-per-request log can carry it
    without re-deriving it or reading the response body
    (docs/modules/logging_request_tracing.md #4)."""

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        request.state.error_code = exc.code
        _log_error(
            request,
            logging.ERROR if exc.status_code >= 500 else logging.INFO,
            f"{request.method} {request.url.path} -> {exc.status_code} {exc.code}",
            method=request.method,
            path=request.url.path,
            status_code=exc.status_code,
            error_code=exc.code,
            error_message=exc.message,
        )
        return _error_response(exc.status_code, exc.code, exc.message, exc.fields)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Every invalid field, not just the first -- docs/modules/api_error_handling.md
        # #7 ("field-level errors so the UI can show them beside the
        # relevant field"), closing the gap found in jdk_clean's
        # equivalent (only exc.errors()[0] was ever surfaced there).
        fields: dict[str, str] = {}
        for error in exc.errors():
            field = ".".join(str(part) for part in error["loc"] if part not in ("body", "query", "path"))
            if error["type"] == "value_error":
                # Our own @field_validator raised ValueError with an
                # already-specific, user-facing message -- surface it
                # verbatim rather than Pydantic's generic wrapper text.
                message = str(error.get("ctx", {}).get("error") or error["msg"].removeprefix("Value error, "))
            else:
                # A malformed value Pydantic couldn't even parse --
                # its raw msg/type are internal jargon, not meant for
                # the person filling in the form. Never the offending
                # value itself (error["input"]) -- it could be a
                # password or other sensitive field
                # (docs/modules/logging_request_tracing.md #7).
                message = "This value is invalid."
            fields[field or "_"] = message
        request.state.error_code = "VALIDATION_ERROR"
        _log_error(
            request,
            logging.INFO,
            f"{request.method} {request.url.path} -> 422 VALIDATION_ERROR",
            method=request.method,
            path=request.url.path,
            status_code=422,
            error_code="VALIDATION_ERROR",
            invalid_fields=list(fields.keys()),
        )
        return _error_response(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "VALIDATION_ERROR",
            "Please review the highlighted fields.",
            fields,
        )

    @app.exception_handler(IntegrityError)
    async def integrity_error_handler(request: Request, exc: IntegrityError) -> JSONResponse:
        request.state.error_code = "CONFLICT"
        _log_error(
            request,
            logging.ERROR,
            f"{request.method} {request.url.path} -> integrity error",
            method=request.method,
            path=request.url.path,
            status_code=status.HTTP_409_CONFLICT,
            error_code="CONFLICT",
            exc_info=True,
        )
        return _error_response(
            status.HTTP_409_CONFLICT,
            "CONFLICT",
            "This action conflicts with existing data. Please refresh and try again.",
        )

    @app.exception_handler(SQLAlchemyError)
    async def db_error_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        request.state.error_code = "SERVER_ERROR"
        _log_error(
            request,
            logging.ERROR,
            f"{request.method} {request.url.path} -> database error",
            method=request.method,
            path=request.url.path,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_code="SERVER_ERROR",
            exc_info=True,
        )
        return _error_response(status.HTTP_500_INTERNAL_SERVER_ERROR, "SERVER_ERROR", "A database error occurred. Please try again.")

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        # A safety net, not the primary path -- route/service code should
        # always raise an AppError subclass instead. Catches anything
        # that doesn't (a stray raw HTTPException, or a framework-internal
        # one such as an unmatched route's 404) so it still comes back
        # through the standard envelope rather than FastAPI's default
        # {"detail": ...} shape (the exact drift found in jdk_clean --
        # see docs/audit/API_ERROR_HANDLING_AUDIT.md).
        code = _STATUS_TO_CODE.get(exc.status_code, "SERVER_ERROR" if exc.status_code >= 500 else "BUSINESS_RULE_ERROR")
        message = exc.detail if isinstance(exc.detail, str) else "The request could not be processed."
        request.state.error_code = code
        _log_error(
            request,
            logging.ERROR if exc.status_code >= 500 else logging.INFO,
            f"{request.method} {request.url.path} -> {exc.status_code} {code}",
            method=request.method,
            path=request.url.path,
            status_code=exc.status_code,
            error_code=code,
            error_message=message,
        )
        return _error_response(exc.status_code, code, message)

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        request.state.error_code = "SERVER_ERROR"
        _log_error(
            request,
            logging.ERROR,
            f"{request.method} {request.url.path} -> unhandled exception",
            method=request.method,
            path=request.url.path,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_code="SERVER_ERROR",
            error_type=type(exc).__name__,
            exc_info=True,
        )
        return _error_response(status.HTTP_500_INTERNAL_SERVER_ERROR, "SERVER_ERROR", "Something went wrong. Please try again.")
