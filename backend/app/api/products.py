from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin
from app.core.database import get_db
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.id_formats import PRODUCT_CODE
from app.core.list_query import apply_sort, paginate
from app.core.search import apply_keyword_filter
from app.models.audit_event import (
    MASTER_DATA_MODULE,
    PRODUCT_CREATED,
    PRODUCT_STATUS_CHANGED,
    PRODUCT_UPDATED,
)
from app.models.category import PRODUCT
from app.models.product import Product
from app.models.unit import UnitOfMeasure
from app.models.user import User
from app.schemas.product import (
    ProductCreateRequest,
    ProductOut,
    ProductStatusChangeRequest,
    ProductUpdateRequest,
)
from app.schemas.pagination import PaginatedResponse
from app.services import audit_service, category_service

router = APIRouter(prefix="/api/products", tags=["products"])

# See app/api/users.py's _SORT_FIELDS for the reasoning.
_SORT_FIELDS = {
    "code": Product.code,
    "name": Product.name,
    "selling_price": Product.selling_price,
    "created_at": Product.created_at,
}

_MAX_CODE_ATTEMPTS = 5


def _generate_product_code(db: Session, organisation_id: int) -> str:
    existing = db.query(Product).filter(Product.organisation_id == organisation_id).count()
    return PRODUCT_CODE.format(existing + 1)


def _get_product_in_org(db: Session, product_id: int, organisation_id: int) -> Product:
    product = (
        db.query(Product)
        .filter(Product.id == product_id, Product.organisation_id == organisation_id)
        .first()
    )
    if product is None:
        # 404 whether the id doesn't exist at all or belongs to another
        # organisation -- never confirm another organisation's product id
        # (docs/modules/organisation.md #3).
        raise NotFoundError("Product not found.")
    return product


def _resolve_active_unit(db: Session, unit_of_measure_id: int, organisation_id: int) -> UnitOfMeasure:
    unit = (
        db.query(UnitOfMeasure)
        .filter(
            UnitOfMeasure.id == unit_of_measure_id,
            UnitOfMeasure.organisation_id == organisation_id,
            UnitOfMeasure.is_active.is_(True),
        )
        .first()
    )
    if unit is None:
        raise ValidationError(
            "unit_of_measure_id must be an active unit of measure in your organisation.",
            fields={"unit_of_measure_id": "Not a valid active unit of measure in your organisation."},
        )
    return unit


@router.get("", response_model=PaginatedResponse[ProductOut])
def list_products(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    sort_by: str | None = Query(None),
    sort_direction: Literal["asc", "desc"] = Query("asc"),
    include_inactive: bool = Query(False),
    q: str | None = Query(None, max_length=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PaginatedResponse[ProductOut]:
    """Scoped to the caller's own organisation only. Open to any
    authenticated organisation member, same as every other master --
    Product is reference data every future Feasibility/Quotation/Order/
    BOM/Production/Inventory consumer needs to look up, not a privileged
    view; only mutations are admin-gated. q searches name/code."""
    query = db.query(Product).filter(Product.organisation_id == current_user.organisation_id)
    if not include_inactive:
        query = query.filter(Product.is_active.is_(True))
    query = apply_keyword_filter(query, q, Product.name, Product.code)
    query = apply_sort(query, sort_by, sort_direction, _SORT_FIELDS, default=Product.id)

    products, pagination = paginate(query, page, page_size)
    return PaginatedResponse(data=[ProductOut.model_validate(p) for p in products], pagination=pagination)


@router.get("/{product_id}", response_model=ProductOut)
def get_product(
    product_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> Product:
    return _get_product_in_org(db, product_id, current_user.organisation_id)


@router.post("", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
def create_product(
    payload: ProductCreateRequest,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Product:
    """Admin-gated (same shape as every other master-data mutation).
    `code` is system-generated and retried against a collision, same
    pattern Supplier/Customer already use (per explicit user instruction,
    superseding this module's original caller-supplied code -- see
    docs/audit/PRODUCTS_AUDIT.md #2 for the now-superseded jdk_clean
    precedent)."""
    category_service.resolve_category(db, payload.category_id, admin.organisation_id, PRODUCT)
    _resolve_active_unit(db, payload.unit_of_measure_id, admin.organisation_id)

    product: Product | None = None
    last_error: IntegrityError | None = None
    for _ in range(_MAX_CODE_ATTEMPTS):
        code = _generate_product_code(db, admin.organisation_id)
        product = Product(
            organisation_id=admin.organisation_id,
            code=code,
            name=payload.name,
            category_id=payload.category_id,
            unit_of_measure_id=payload.unit_of_measure_id,
            description=payload.description,
            selling_price=payload.selling_price,
            manufacturing_lead_time_days=payload.manufacturing_lead_time_days,
            customer_lead_time_days=payload.customer_lead_time_days,
        )
        db.add(product)
        try:
            db.flush()
            last_error = None
            break
        except IntegrityError as exc:
            db.rollback()
            last_error = exc
    if last_error is not None or product is None:
        raise ConflictError(
            "A product with this name already exists, or a unique code could not be generated."
        ) from last_error

    audit_service.log_event(
        db,
        action=PRODUCT_CREATED,
        module=MASTER_DATA_MODULE,
        organisation_id=admin.organisation_id,
        actor_user_id=admin.id,
        entity_type="product",
        entity_id=product.id,
        result="success",
        details=f"code: {product.code}, name: {product.name}",
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    db.refresh(product)
    return product


@router.patch("/{product_id}", response_model=ProductOut)
def update_product(
    product_id: int,
    payload: ProductUpdateRequest,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Product:
    """Admin-gated partial update. is_active has its own endpoint below.
    `code` cannot be changed here -- see ProductUpdateRequest."""
    product = _get_product_in_org(db, product_id, admin.organisation_id)

    updates = payload.model_dump(exclude_unset=True)
    # Unchanged is fine even if the category has since been deactivated.
    if "category_id" in updates and updates["category_id"] != product.category_id:
        category_service.resolve_category(db, updates["category_id"], admin.organisation_id, PRODUCT)
    if "unit_of_measure_id" in updates:
        _resolve_active_unit(db, updates["unit_of_measure_id"], admin.organisation_id)

    before = {field: getattr(product, field) for field in updates}
    for field, value in updates.items():
        setattr(product, field, value)
    db.add(product)

    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("A product with this name already exists.") from exc

    changes = audit_service.diff_fields(before, updates)
    if changes:
        audit_service.log_event(
            db,
            action=PRODUCT_UPDATED,
            module=MASTER_DATA_MODULE,
            organisation_id=admin.organisation_id,
            actor_user_id=admin.id,
            entity_type="product",
            entity_id=product.id,
            result="success",
            details=audit_service.format_changes(changes),
            ip_address=request.client.host if request.client else None,
        )
    db.commit()
    db.refresh(product)
    return product


@router.patch("/{product_id}/status", response_model=ProductOut)
def change_product_status(
    product_id: int,
    payload: ProductStatusChangeRequest,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Product:
    """Admin-gated activate/deactivate. No delete guard is needed yet --
    nothing in jdk_erp references `products` (BOM/Quotation/Order/
    Production/Inventory are all unbuilt); jdk_clean itself has no delete
    guard on Product either despite those consumers existing there
    (docs/audit/PRODUCTS_AUDIT.md #11, a gap noted for whichever module
    is built first against a referenced product). Deactivating only
    governs whether the product can be *newly selected* -- the same rule
    already established for every other master."""
    product = _get_product_in_org(db, product_id, admin.organisation_id)
    product.is_active = payload.is_active
    db.add(product)

    audit_service.log_event(
        db,
        action=PRODUCT_STATUS_CHANGED,
        module=MASTER_DATA_MODULE,
        organisation_id=admin.organisation_id,
        actor_user_id=admin.id,
        entity_type="product",
        entity_id=product.id,
        result="success",
        details=f"is_active: {payload.is_active}",
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    db.refresh(product)
    return product
