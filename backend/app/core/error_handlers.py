import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.errors import AppError
from app.core.request_context import get_request_id

# A dedicated logger with its own explicit handler (set up in
# register_exception_handlers), rather than relying on ambient
# root-logger/process-manager behaviour -- jdk_clean's equivalent
# ("app") had no configured handler anywhere in its own repo (see
# docs/audit/API_ERROR_HANDLING_AUDIT.md).
logger = logging.getLogger("jdk.errors")

_STATUS_TO_CODE = {
    status.HTTP_401_UNAUTHORIZED: "AUTHENTICATION_ERROR",
    status.HTTP_403_FORBIDDEN: "ACCESS_DENIED",
    status.HTTP_404_NOT_FOUND: "NOT_FOUND",
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


def register_exception_handlers(app: FastAPI) -> None:
    """One chokepoint for every failure shape
    (docs/modules/api_error_handling.md #1) -- no module registers its
    own error handling."""
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        log_line = "request_id=%s %s %s -> %s %s: %s" % (
            get_request_id(),
            request.method,
            request.url.path,
            exc.status_code,
            exc.code,
            exc.message,
        )
        if exc.status_code >= 500:
            logger.error(log_line, exc_info=True)
        else:
            logger.info(log_line)
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
                # the person filling in the form.
                message = "This value is invalid."
            fields[field or "_"] = message
        logger.info(
            "request_id=%s %s %s -> 422 VALIDATION_ERROR: %s",
            get_request_id(),
            request.method,
            request.url.path,
            fields,
        )
        return _error_response(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "VALIDATION_ERROR",
            "Please review the highlighted fields.",
            fields,
        )

    @app.exception_handler(IntegrityError)
    async def integrity_error_handler(request: Request, exc: IntegrityError) -> JSONResponse:
        logger.error(
            "request_id=%s %s %s -> integrity error", get_request_id(), request.method, request.url.path, exc_info=True
        )
        return _error_response(
            status.HTTP_409_CONFLICT,
            "CONFLICT",
            "This action conflicts with existing data. Please refresh and try again.",
        )

    @app.exception_handler(SQLAlchemyError)
    async def db_error_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        logger.error(
            "request_id=%s %s %s -> database error", get_request_id(), request.method, request.url.path, exc_info=True
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
        logger.info(
            "request_id=%s %s %s -> %s %s: %s",
            get_request_id(),
            request.method,
            request.url.path,
            exc.status_code,
            code,
            message,
        )
        return _error_response(exc.status_code, code, message)

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error(
            "request_id=%s %s %s -> unhandled exception",
            get_request_id(),
            request.method,
            request.url.path,
            exc_info=True,
        )
        return _error_response(status.HTTP_500_INTERNAL_SERVER_ERROR, "SERVER_ERROR", "Something went wrong. Please try again.")
