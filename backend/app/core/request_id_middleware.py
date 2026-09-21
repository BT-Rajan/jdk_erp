from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.request_context import new_request_id, set_request_id


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Generates the per-request correlation id as early as possible, so
    it's available to every exception handler and log line for the rest
    of the request (docs/modules/api_error_handling.md #4/#5). Also
    echoed as a response header, on success or failure alike, so a
    client can always report it."""

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = new_request_id()
        set_request_id(request_id)
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
