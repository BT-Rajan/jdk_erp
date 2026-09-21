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
from app.core.security_headers import SecurityHeadersMiddleware

app = FastAPI(title="JDK ERP API")

# Order matters: middleware runs outside-in on the request, inside-out on
# the response, so HTTPS redirect (outermost) must never see a request
# CORS/security-headers haven't touched the response of yet -- Starlette
# applies them in the reverse of this add order, so this is correct as
# written (last added runs first on the way in).
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

app.include_router(audit_events_router)
app.include_router(auth_router)
app.include_router(organisations_router)
app.include_router(permissions_router)
app.include_router(teams_router)
app.include_router(users_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
