from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware

from app.api.audit_events import router as audit_events_router
from app.api.auth import router as auth_router
from app.api.organisations import router as organisations_router
from app.api.permissions import router as permissions_router
from app.api.teams import router as teams_router
from app.api.users import router as users_router
from app.core.config import settings
from app.core.error_handlers import register_exception_handlers
from app.core.logging import configure_logging
from app.core.request_id_middleware import RequestIDMiddleware
from app.core.request_logging_middleware import RequestLoggingMiddleware
from app.core.security_headers import SecurityHeadersMiddleware

configure_logging()

app = FastAPI(title="JDK ERP API")

register_exception_handlers(app)

# Order matters: middleware runs outside-in on the request, inside-out on
# the response -- Starlette applies them in the reverse of this add
# order, so the *last* one added here is the *first* to see the request.
# RequestIDMiddleware goes last so the request id (and user/organisation
# context reset) is set before anything else, including the exception
# handlers above and RequestLoggingMiddleware, can run. RequestLoggingMiddleware
# goes second-to-last so it wraps the whole request (including exception
# handling) and its duration_ms covers the full lifecycle
# (docs/modules/logging_request_tracing.md #2/#4).
if settings.FORCE_HTTPS:
    app.add_middleware(HTTPSRedirectMiddleware)

app.add_middleware(SecurityHeadersMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(RequestIDMiddleware)

app.include_router(audit_events_router)
app.include_router(auth_router)
app.include_router(organisations_router)
app.include_router(permissions_router)
app.include_router(teams_router)
app.include_router(users_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
