from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import settings


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Centralized security headers (docs/modules/session_security.md
    #11) -- set in one place, not scattered per-endpoint. This is a JSON
    API with no HTML rendering of its own, so the baseline is maximally
    strict; revisit the CSP specifically once a frontend serves HTML from
    this origin."""

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        if settings.FORCE_HTTPS:
            # Only advertised when HTTPS is actually enforced -- an HSTS
            # header over plain HTTP is meaningless and, if a browser
            # caches it, can break a plain-HTTP dev environment later.
            response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        return response
