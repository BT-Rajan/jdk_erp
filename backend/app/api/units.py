from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin
from app.core.database import get_db
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.list_query import apply_sort, paginate
from app.core.search import apply_keyword_filter
from app.models.audit_event import (
    MASTER_DATA_MODULE,
    UNIT_CREATED,
    UNIT_STATUS_CHANGED,
    UNIT_UPDATED,
)
from app.models.unit import UnitOfMeasure
from app.models.user import User
from app.schemas.pagination import PaginatedResponse
from app.schemas.unit import (
    UnitOfMeasureCreateRequest,
    UnitOfMeasureOut,
    UnitOfMeasureStatusChangeRequest,
    UnitOfMeasureUpdateRequest,
)
from app.services import audit_service

router = APIRouter(prefix="/api/units-of-measure", tags=["units-of-measure"])

# See app/api/users.py's _SORT_FIELDS for the reasoning.
_SORT_FIELDS = {
    "name": UnitOfMeasure.name,
    "code": UnitOfMeasure.code,
    "created_at": UnitOfMeasure.created_at,
}


def _get_unit_in_org(db: Session, unit_id: int, organisation_id: int) -> UnitOfMeasure:
    unit = (
        db.query(UnitOfMeasure)
        .filter(UnitOfMeasure.id == unit_id, UnitOfMeasure.organisation_id == organisation_id)
        .first()
    )
    if unit is None:
        # 404 whether the id doesn't exist at all or belongs to another
        # organisation -- never confirm another organisation's unit id
        # (docs/modules/organisation.md #3).
        raise NotFoundError("Unit of measure not found.")
    return unit


@router.get("", response_model=PaginatedResponse[UnitOfMeasureOut])
def list_units(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    sort_by: str | None = Query(None),
    sort_direction: Literal["asc", "desc"] = Query("asc"),
    include_inactive: bool = Query(False),
    q: str | None = Query(None, max_length=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PaginatedResponse[UnitOfMeasureOut]:
    """Scoped to the caller's own organisation only
    (docs/modules/units_of_measure.md #6 -- organisation-owned, not a
    controlled global list, an explicit decision since jdk_clean's own
    design gives no reason to preserve a global list here). Open to any
    authenticated organisation member, same as Categories/Teams/Users --
    read-only reference data every future module that records a quantity
    needs to look up. q searches name/code, applied after the
    organisation/is_active filters. page/sort follow the common list
    contract (docs/audit/TABLES_FORMS_MODALS_FILTERS_AUDIT.md)."""
    query = db.query(UnitOfMeasure).filter(UnitOfMeasure.organisation_id == current_user.organisation_id)
    if not include_inactive:
        query = query.filter(UnitOfMeasure.is_active.is_(True))
    query = apply_keyword_filter(query, q, UnitOfMeasure.name, UnitOfMeasure.code)
    query = apply_sort(query, sort_by, sort_direction, _SORT_FIELDS, default=UnitOfMeasure.id)

    units, pagination = paginate(query, page, page_size)
    return PaginatedResponse(data=[UnitOfMeasureOut.model_validate(u) for u in units], pagination=pagination)


@router.get("/{unit_id}", response_model=UnitOfMeasureOut)
def get_unit(
    unit_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> UnitOfMeasure:
    return _get_unit_in_org(db, unit_id, current_user.organisation_id)


@router.post("", response_model=UnitOfMeasureOut, status_code=status.HTTP_201_CREATED)
def create_unit(
    payload: UnitOfMeasureCreateRequest,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> UnitOfMeasure:
    """Admin-gated (docs/modules/units_of_measure.md #7), the same RBAC
    gate every other master-data mutation in this app uses -- no
    unit-specific authorization layer. organisation_id always comes from
    the authenticated admin, never the request body."""
    unit = UnitOfMeasure(
        organisation_id=admin.organisation_id,
        name=payload.name,
        code=payload.code,
        description=payload.description,
        dimension=payload.dimension,
        conversion_factor_to_base=payload.conversion_factor_to_base,
    )
    db.add(unit)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("A unit with this name or code already exists.") from exc

    audit_service.log_event(
        db,
        action=UNIT_CREATED,
        module=MASTER_DATA_MODULE,
        organisation_id=admin.organisation_id,
        actor_user_id=admin.id,
        entity_type="unit_of_measure",
        entity_id=unit.id,
        result="success",
        details=f"name: {unit.name} ({unit.code})",
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    db.refresh(unit)
    return unit


@router.patch("/{unit_id}", response_model=UnitOfMeasureOut)
def update_unit(
    unit_id: int,
    payload: UnitOfMeasureUpdateRequest,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> UnitOfMeasure:
    """Admin-gated partial update, same shape as PATCH /api/categories/{id}.
    is_active is deliberately not editable here -- see
    change_unit_status below."""
    unit = _get_unit_in_org(db, unit_id, admin.organisation_id)

    updates = payload.model_dump(exclude_unset=True)
    before = {field: getattr(unit, field) for field in updates}
    for field, value in updates.items():
        setattr(unit, field, value)

    if "dimension" in updates or "conversion_factor_to_base" in updates:
        # A partial update can only see the fields actually sent -- check
        # the *merged* post-update state so a caller can't silently leave
        # a half-configured dimension/factor pair by omitting one side
        # (docs/modules/boms.md #3).
        if (unit.dimension is None) != (unit.conversion_factor_to_base is None):
            raise ValidationError(
                "dimension and conversion_factor_to_base must be provided together, or not at all.",
                fields={"conversion_factor_to_base": "Must be set together with dimension, or both left unset."},
            )
        if unit.conversion_factor_to_base is not None and unit.conversion_factor_to_base <= 0:
            raise ValidationError(
                "conversion_factor_to_base must be greater than zero.",
                fields={"conversion_factor_to_base": "Must be greater than zero."},
            )

    db.add(unit)

    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("A unit with this name or code already exists.") from exc

    changes = audit_service.diff_fields(before, updates)
    if changes:
        audit_service.log_event(
            db,
            action=UNIT_UPDATED,
            module=MASTER_DATA_MODULE,
            organisation_id=admin.organisation_id,
            actor_user_id=admin.id,
            entity_type="unit_of_measure",
            entity_id=unit.id,
            result="success",
            details=audit_service.format_changes(changes),
            ip_address=request.client.host if request.client else None,
        )
    db.commit()
    db.refresh(unit)
    return unit


@router.patch("/{unit_id}/status", response_model=UnitOfMeasureOut)
def change_unit_status(
    unit_id: int,
    payload: UnitOfMeasureStatusChangeRequest,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> UnitOfMeasure:
    """Admin-gated activate/deactivate (docs/modules/units_of_measure.md #8).
    No self-lockout concern -- deactivating a unit only affects whether
    it can be picked for new records, never anyone's ability to sign in."""
    unit = _get_unit_in_org(db, unit_id, admin.organisation_id)
    unit.is_active = payload.is_active
    db.add(unit)

    audit_service.log_event(
        db,
        action=UNIT_STATUS_CHANGED,
        module=MASTER_DATA_MODULE,
        organisation_id=admin.organisation_id,
        actor_user_id=admin.id,
        entity_type="unit_of_measure",
        entity_id=unit.id,
        result="success",
        details=f"is_active: {payload.is_active}",
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    db.refresh(unit)
    return unit
