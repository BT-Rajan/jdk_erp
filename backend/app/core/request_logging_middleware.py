import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import settings
from app.core.logging import get_logger, log

logger = get_logger("request")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """One structured log line per completed request
    (docs/modules/logging_request_tracing.md #4/#8) -- method, route,
    status, duration_ms, and the error code an exception handler left on
    request.state (if any), never the request/response body. Placed
    after RequestIDMiddleware in app/main.py's add order so it runs
    *outside* it (sees the same request_id already set) and wraps the
    whole request including exception handling, so duration_ms covers
    the full lifecycle.

    Level follows docs/modules/logging_request_tracing.md #1's own
    definitions: a 5xx is a failure requiring investigation (ERROR, in
    addition to the specific error already logged by
    app/core/error_handlers.py); a request slower than
    SLOW_REQUEST_THRESHOLD_MS is unusual but handled (WARN); everything
    else is an important normal event (INFO)."""

    async def dispatch(self, request: Request, call_next) -> Response:
        started_at = time.perf_counter()
        # Starlette's BaseHTTPMiddleware has a well-known quirk when
        # several of them are stacked (as here): once a registered
        # exception handler converts a downstream exception into a
        # response, that conversion doesn't reliably survive back
        # through an *intermediate* middleware's call_next() -- the raw
        # exception re-propagates through each one instead, only
        # actually becoming a response at Starlette's own outermost
        # ServerErrorMiddleware. Left unhandled, this middleware would
        # silently skip its own completion log line for exactly the
        # crash requests #6/#11 care about most -- so log here too, then
        # re-raise unchanged so the real response-building is untouched.
        try:
            response = await call_next(request)
        except Exception:
            self._log_completion(request, started_at, status_code=500, exc_info=True)
            raise

        self._log_completion(request, started_at, status_code=response.status_code)
        return response

    def _log_completion(self, request: Request, started_at: float, *, status_code: int, exc_info: bool = False) -> None:
        duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
        route = request.scope.get("route")
        endpoint = route.path if route is not None else request.url.path
        # Read from request.state, not the user_id/organisation_id
        # ContextVars -- this middleware's own context never sees a
        # mutation made inside call_next()'s separate task (see
        # app/api/deps.py's get_current_user for why).
        error_code = getattr(request.state, "error_code", None)
        user_id = getattr(request.state, "user_id", None)
        organisation_id = getattr(request.state, "organisation_id", None)

        if status_code >= 500:
            level = logging.ERROR
        elif duration_ms >= settings.SLOW_REQUEST_THRESHOLD_MS:
            level = logging.WARNING
        else:
            level = logging.INFO

        log(
            logger,
            level,
            f"{request.method} {endpoint} -> {status_code}",
            exc_info=exc_info,
            method=request.method,
            endpoint=endpoint,
            status_code=status_code,
            duration_ms=duration_ms,
            error_code=error_code,
            user_id=user_id,
            organisation_id=organisation_id,
        )
