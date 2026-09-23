from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin
from app.core.database import get_db
from app.core.errors import ConflictError, NotFoundError
from app.core.id_formats import SUPPLIER_ID
from app.core.list_query import apply_sort, paginate
from app.core.search import apply_keyword_filter
from app.models.audit_event import (
    MASTER_DATA_MODULE,
    SUPPLIER_CREATED,
    SUPPLIER_STATUS_CHANGED,
    SUPPLIER_UPDATED,
)
from app.models.supplier import Supplier
from app.models.user import User
from app.schemas.supplier import (
    SupplierCreateRequest,
    SupplierOut,
    SupplierStatusChangeRequest,
    SupplierUpdateRequest,
)
from app.schemas.pagination import PaginatedResponse
from app.services import audit_service

router = APIRouter(prefix="/api/suppliers", tags=["suppliers"])

# See app/api/users.py's _SORT_FIELDS for the reasoning.
_SORT_FIELDS = {
    "code": Supplier.code,
    "name": Supplier.name,
    "created_at": Supplier.created_at,
}

_MAX_CODE_ATTEMPTS = 5


def _get_supplier_in_org(db: Session, supplier_id: int, organisation_id: int) -> Supplier:
    supplier = (
        db.query(Supplier)
        .filter(Supplier.id == supplier_id, Supplier.organisation_id == organisation_id)
        .first()
    )
    if supplier is None:
        # 404 whether the id doesn't exist at all or belongs to another
        # organisation -- never confirm another organisation's supplier id
        # (docs/modules/organisation.md #3).
        raise NotFoundError("Supplier not found.")
    return supplier


def _generate_supplier_code(db: Session, organisation_id: int) -> str:
    existing = db.query(Supplier).filter(Supplier.organisation_id == organisation_id).count()
    return SUPPLIER_ID.format(existing + 1)


@router.get("", response_model=PaginatedResponse[SupplierOut])
def list_suppliers(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    sort_by: str | None = Query(None),
    sort_direction: Literal["asc", "desc"] = Query("asc"),
    include_inactive: bool = Query(False),
    q: str | None = Query(None, max_length=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PaginatedResponse[SupplierOut]:
    """Scoped to the caller's own organisation only (docs/modules/suppliers.md
    #3). Open to any authenticated organisation member, same as
    Categories/Units -- a supplier is reference data Procurement (and
    anyone raising a purchase request) needs to look up, not a privileged
    view; only mutations are admin-gated. q searches name/code/
    contact_person/phone."""
    query = db.query(Supplier).filter(Supplier.organisation_id == current_user.organisation_id)
    if not include_inactive:
        query = query.filter(Supplier.is_active.is_(True))
    query = apply_keyword_filter(query, q, Supplier.name, Supplier.code, Supplier.contact_person, Supplier.phone)
    query = apply_sort(query, sort_by, sort_direction, _SORT_FIELDS, default=Supplier.id)

    suppliers, pagination = paginate(query, page, page_size)
    return PaginatedResponse(data=[SupplierOut.model_validate(s) for s in suppliers], pagination=pagination)


@router.get("/{supplier_id}", response_model=SupplierOut)
def get_supplier(
    supplier_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> Supplier:
    return _get_supplier_in_org(db, supplier_id, current_user.organisation_id)


@router.post("", response_model=SupplierOut, status_code=status.HTTP_201_CREATED)
def create_supplier(
    payload: SupplierCreateRequest,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Supplier:
    """Admin-gated (docs/modules/suppliers.md #5) -- unlike Customer,
    onboarding a supplier is a master-data administration action here,
    not ordinary operational work anyone can do; jdk_clean gates it by
    department-level page permission instead, but at ~10 suppliers per
    organisation the plain admin gate every other master in this app uses
    is simpler and sufficient (docs/audit/SUPPLIERS_AUDIT.md #9)."""
    if payload.phone is not None:
        duplicate = (
            db.query(Supplier)
            .filter(Supplier.organisation_id == admin.organisation_id, Supplier.phone == payload.phone)
            .first()
        )
        if duplicate is not None:
            raise ConflictError("A supplier with this phone number already exists.")

    supplier: Supplier | None = None
    last_error: IntegrityError | None = None
    for _ in range(_MAX_CODE_ATTEMPTS):
        code = _generate_supplier_code(db, admin.organisation_id)
        supplier = Supplier(
            organisation_id=admin.organisation_id,
            code=code,
            name=payload.name,
            contact_person=payload.contact_person,
            phone=payload.phone,
            email=payload.email,
            address=payload.address,
        )
        db.add(supplier)
        try:
            db.flush()
            last_error = None
            break
        except IntegrityError as exc:
            db.rollback()
            last_error = exc
    if last_error is not None or supplier is None:
        raise ConflictError(
            "A supplier with this name or phone number already exists, or a unique code could not be generated."
        ) from last_error

    audit_service.log_event(
        db,
        action=SUPPLIER_CREATED,
        module=MASTER_DATA_MODULE,
        organisation_id=admin.organisation_id,
        actor_user_id=admin.id,
        entity_type="supplier",
        entity_id=supplier.id,
        result="success",
        details=f"code: {supplier.code}, name: {supplier.name}",
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    db.refresh(supplier)
    return supplier


@router.patch("/{supplier_id}", response_model=SupplierOut)
def update_supplier(
    supplier_id: int,
    payload: SupplierUpdateRequest,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Supplier:
    """Admin-gated partial update, same shape as PATCH /api/customers/{id}.
    is_active has its own endpoint below."""
    supplier = _get_supplier_in_org(db, supplier_id, admin.organisation_id)

    updates = payload.model_dump(exclude_unset=True)
    before = {field: getattr(supplier, field) for field in updates}
    for field, value in updates.items():
        setattr(supplier, field, value)
    db.add(supplier)

    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("A supplier with this name or phone number already exists.") from exc

    changes = audit_service.diff_fields(before, updates)
    if changes:
        audit_service.log_event(
            db,
            action=SUPPLIER_UPDATED,
            module=MASTER_DATA_MODULE,
            organisation_id=admin.organisation_id,
            actor_user_id=admin.id,
            entity_type="supplier",
            entity_id=supplier.id,
            result="success",
            details=audit_service.format_changes(changes),
            ip_address=request.client.host if request.client else None,
        )
    db.commit()
    db.refresh(supplier)
    return supplier


@router.patch("/{supplier_id}/status", response_model=SupplierOut)
def change_supplier_status(
    supplier_id: int,
    payload: SupplierStatusChangeRequest,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Supplier:
    """Admin-gated activate/deactivate (docs/modules/suppliers.md #6). No
    delete guard is needed -- there is deliberately no hard delete here,
    same as every other master; deactivating only affects whether a
    supplier can be picked for new records."""
    supplier = _get_supplier_in_org(db, supplier_id, admin.organisation_id)
    supplier.is_active = payload.is_active
    db.add(supplier)

    audit_service.log_event(
        db,
        action=SUPPLIER_STATUS_CHANGED,
        module=MASTER_DATA_MODULE,
        organisation_id=admin.organisation_id,
        actor_user_id=admin.id,
        entity_type="supplier",
        entity_id=supplier.id,
        result="success",
        details=f"is_active: {payload.is_active}",
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    db.refresh(supplier)
    return supplier
