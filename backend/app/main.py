from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware

import app.jobs  # noqa: F401 -- registers every job handler (docs/modules/background_jobs.md #1)
from app.api.audit_events import router as audit_events_router
from app.api.auth import router as auth_router
from app.api.boms import router as boms_router
from app.api.categories import router as categories_router
from app.api.communication import router as communication_router
from app.api.customers import router as customers_router
from app.api.files import router as files_router
from app.api.jobs import router as jobs_router
from app.api.notifications import router as notifications_router
from app.api.organisations import router as organisations_router
from app.api.machines import router as machines_router
from app.api.permissions import router as permissions_router
from app.api.production_lines import router as production_lines_router
from app.api.products import router as products_router
from app.api.purchase_orders import router as purchase_orders_router
from app.api.rfqs import router as rfqs_router
from app.api.document_templates import router as document_templates_router
from app.api.goods_receiving import router as goods_receiving_router
from app.api.finance import router as finance_router
from app.api.raw_material_suppliers import router as raw_material_suppliers_router
from app.api.raw_materials import router as raw_materials_router
from app.api.warehouses import router as warehouses_router
from app.api.suppliers import router as suppliers_router
from app.api.teams import router as teams_router
from app.api.units import router as units_router
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
app.include_router(boms_router)
app.include_router(categories_router)
app.include_router(communication_router)
app.include_router(customers_router)
app.include_router(files_router)
app.include_router(jobs_router)
app.include_router(notifications_router)
app.include_router(organisations_router)
app.include_router(machines_router)
app.include_router(permissions_router)
app.include_router(production_lines_router)
app.include_router(products_router)
app.include_router(purchase_orders_router)
app.include_router(rfqs_router)
app.include_router(document_templates_router)
app.include_router(goods_receiving_router)
app.include_router(finance_router)
app.include_router(raw_material_suppliers_router)
app.include_router(raw_materials_router)
app.include_router(suppliers_router)
app.include_router(warehouses_router)
app.include_router(teams_router)
app.include_router(units_router)
app.include_router(users_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
