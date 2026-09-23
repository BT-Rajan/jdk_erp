from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin
from app.core.database import get_db
from app.core.errors import BusinessRuleError, ConflictError, NotFoundError, ValidationError
from app.core.id_formats import WAREHOUSE_CODE
from app.core.list_query import apply_sort, paginate
from app.core.search import apply_keyword_filter
from app.models.audit_event import (
    MASTER_DATA_MODULE,
    WAREHOUSE_CREATED,
    WAREHOUSE_STATUS_CHANGED,
    WAREHOUSE_UPDATED,
)
from app.models.unit import UnitOfMeasure
from app.models.user import User
from app.models.warehouse import Warehouse
from app.schemas.warehouse import (
    WarehouseCreateRequest,
    WarehouseOut,
    WarehouseStatusChangeRequest,
    WarehouseUpdateRequest,
)
from app.schemas.pagination import PaginatedResponse
from app.services import audit_service

router = APIRouter(prefix="/api/warehouses", tags=["warehouses"])

# See app/api/users.py's _SORT_FIELDS for the reasoning.
_SORT_FIELDS = {
    "code": Warehouse.code,
    "name": Warehouse.name,
    "created_at": Warehouse.created_at,
}

_MAX_CODE_ATTEMPTS = 5


def _generate_warehouse_code(db: Session, organisation_id: int) -> str:
    existing = db.query(Warehouse).filter(Warehouse.organisation_id == organisation_id).count()
    try:
        return WAREHOUSE_CODE.format(existing + 1)
    except ValueError as exc:
        raise BusinessRuleError(
            "The maximum number of warehouses has been reached. Contact support to raise this limit."
        ) from exc


def _get_warehouse_in_org(db: Session, warehouse_id: int, organisation_id: int) -> Warehouse:
    warehouse = (
        db.query(Warehouse).filter(Warehouse.id == warehouse_id, Warehouse.organisation_id == organisation_id).first()
    )
    if warehouse is None:
        raise NotFoundError("Warehouse not found.")
    return warehouse


def _resolve_active_unit(db: Session, unit_of_measure_id: int, organisation_id: int) -> UnitOfMeasure:
    """A direct, all-in-one-filter query so a missing, inactive, and
    cross-organisation unit_of_measure_id are all rejected the same way
    -- 422, never a 404 leaking whether the id exists at all -- matching
    Product/RawMaterial/Machine's own FK validation exactly."""
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
            "storage_area_unit_of_measure_id must be an active unit of measure in your organisation.",
            fields={"storage_area_unit_of_measure_id": "Not a valid active unit of measure in your organisation."},
        )
    return unit


@router.get("", response_model=PaginatedResponse[WarehouseOut])
def list_warehouses(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    sort_by: str | None = Query(None),
    sort_direction: Literal["asc", "desc"] = Query("asc"),
    include_inactive: bool = Query(False),
    q: str | None = Query(None, max_length=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PaginatedResponse[WarehouseOut]:
    """Scoped to the caller's own organisation only. Open to any
    authenticated organisation member -- a future Inventory consumer
    (and anyone checking configured storage capacity) needs to look this
    up; only mutations are admin-gated."""
    query = db.query(Warehouse).filter(Warehouse.organisation_id == current_user.organisation_id)
    if not include_inactive:
        query = query.filter(Warehouse.is_active.is_(True))
    query = apply_keyword_filter(query, q, Warehouse.name, Warehouse.code)
    query = apply_sort(query, sort_by, sort_direction, _SORT_FIELDS, default=Warehouse.id)

    warehouses, pagination = paginate(query, page, page_size)
    return PaginatedResponse(data=[WarehouseOut.model_validate(w) for w in warehouses], pagination=pagination)


@router.get("/{warehouse_id}", response_model=WarehouseOut)
def get_warehouse(
    warehouse_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> Warehouse:
    return _get_warehouse_in_org(db, warehouse_id, current_user.organisation_id)


@router.post("", response_model=WarehouseOut, status_code=status.HTTP_201_CREATED)
def create_warehouse(
    payload: WarehouseCreateRequest,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Warehouse:
    """Admin-gated. `code` is system-generated and retried against a
    collision, with no update path (see WarehouseUpdateRequest). No
    singleton constraint is enforced -- ordinary CRUD already produces
    "exactly one" today; see app/models/warehouse.py's docstring."""
    _resolve_active_unit(db, payload.storage_area_unit_of_measure_id, admin.organisation_id)

    warehouse: Warehouse | None = None
    last_error: IntegrityError | None = None
    for _ in range(_MAX_CODE_ATTEMPTS):
        code = _generate_warehouse_code(db, admin.organisation_id)
        warehouse = Warehouse(
            organisation_id=admin.organisation_id,
            code=code,
            name=payload.name,
            total_usable_storage_area=payload.total_usable_storage_area,
            storage_area_unit_of_measure_id=payload.storage_area_unit_of_measure_id,
        )
        db.add(warehouse)
        try:
            db.flush()
            last_error = None
            break
        except IntegrityError as exc:
            db.rollback()
            last_error = exc
    if last_error is not None or warehouse is None:
        raise ConflictError(
            "A warehouse with this name already exists, or a unique code could not be generated."
        ) from last_error

    audit_service.log_event(
        db,
        action=WAREHOUSE_CREATED,
        module=MASTER_DATA_MODULE,
        organisation_id=admin.organisation_id,
        actor_user_id=admin.id,
        entity_type="warehouse",
        entity_id=warehouse.id,
        result="success",
        details=f"code: {warehouse.code}, name: {warehouse.name}, area: {warehouse.total_usable_storage_area}",
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    db.refresh(warehouse)
    return warehouse


@router.patch("/{warehouse_id}", response_model=WarehouseOut)
def update_warehouse(
    warehouse_id: int,
    payload: WarehouseUpdateRequest,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Warehouse:
    """Admin-gated partial update -- this is how an authorised user
    reconfigures total storage capacity without any code change,
    matching Machine's own capacity-reconfiguration pattern. `code`
    cannot be changed here. is_active has its own endpoint below."""
    warehouse = _get_warehouse_in_org(db, warehouse_id, admin.organisation_id)

    updates = payload.model_dump(exclude_unset=True)
    if "storage_area_unit_of_measure_id" in updates:
        _resolve_active_unit(db, updates["storage_area_unit_of_measure_id"], admin.organisation_id)

    before = {field: getattr(warehouse, field) for field in updates}
    for field, value in updates.items():
        setattr(warehouse, field, value)
    db.add(warehouse)

    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("A warehouse with this name already exists.") from exc

    changes = audit_service.diff_fields(before, updates)
    if changes:
        audit_service.log_event(
            db,
            action=WAREHOUSE_UPDATED,
            module=MASTER_DATA_MODULE,
            organisation_id=admin.organisation_id,
            actor_user_id=admin.id,
            entity_type="warehouse",
            entity_id=warehouse.id,
            result="success",
            details=audit_service.format_changes(changes),
            ip_address=request.client.host if request.client else None,
        )
    db.commit()
    db.refresh(warehouse)
    return warehouse


@router.patch("/{warehouse_id}/status", response_model=WarehouseOut)
def change_warehouse_status(
    warehouse_id: int,
    payload: WarehouseStatusChangeRequest,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Warehouse:
    """Admin-gated activate/deactivate. No guard against deactivating the
    only active warehouse is built yet -- there are no inventory
    operations in this codebase for that to break (Inventory doesn't
    exist yet); whichever future Inventory module actually depends on an
    active warehouse to record movements against is responsible for that
    guard (docs/modules/warehouses.md #20). No delete guard either --
    nothing in jdk_erp references `warehouses` yet."""
    warehouse = _get_warehouse_in_org(db, warehouse_id, admin.organisation_id)
    warehouse.is_active = payload.is_active
    db.add(warehouse)

    audit_service.log_event(
        db,
        action=WAREHOUSE_STATUS_CHANGED,
        module=MASTER_DATA_MODULE,
        organisation_id=admin.organisation_id,
        actor_user_id=admin.id,
        entity_type="warehouse",
        entity_id=warehouse.id,
        result="success",
        details=f"is_active: {payload.is_active}",
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    db.refresh(warehouse)
    return warehouse
