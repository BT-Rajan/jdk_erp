from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin
from app.core.database import get_db
from app.core.errors import ConflictError, NotFoundError
from app.core.list_query import apply_sort, paginate
from app.core.search import apply_keyword_filter
from app.models.audit_event import (
    MASTER_DATA_MODULE,
    PRODUCTION_LINE_CREATED,
    PRODUCTION_LINE_STATUS_CHANGED,
    PRODUCTION_LINE_UPDATED,
)
from app.models.production_line import ProductionLine
from app.models.user import User
from app.schemas.production_line import (
    ProductionLineCreateRequest,
    ProductionLineOut,
    ProductionLineStatusChangeRequest,
    ProductionLineUpdateRequest,
)
from app.schemas.pagination import PaginatedResponse
from app.services import audit_service

router = APIRouter(prefix="/api/production-lines", tags=["production-lines"])

# See app/api/users.py's _SORT_FIELDS for the reasoning.
_SORT_FIELDS = {
    "code": ProductionLine.code,
    "name": ProductionLine.name,
    "created_at": ProductionLine.created_at,
}


def _get_production_line_in_org(db: Session, production_line_id: int, organisation_id: int) -> ProductionLine:
    production_line = (
        db.query(ProductionLine)
        .filter(ProductionLine.id == production_line_id, ProductionLine.organisation_id == organisation_id)
        .first()
    )
    if production_line is None:
        # 404 whether the id doesn't exist at all or belongs to another
        # organisation -- never confirm another organisation's id
        # (docs/modules/organisation.md #3).
        raise NotFoundError("Production line not found.")
    return production_line


@router.get("", response_model=PaginatedResponse[ProductionLineOut])
def list_production_lines(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    sort_by: str | None = Query(None),
    sort_direction: Literal["asc", "desc"] = Query("asc"),
    include_inactive: bool = Query(False),
    q: str | None = Query(None, max_length=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PaginatedResponse[ProductionLineOut]:
    """Scoped to the caller's own organisation only. Open to any
    authenticated organisation member, same as every other master --
    only mutations are admin-gated."""
    query = db.query(ProductionLine).filter(ProductionLine.organisation_id == current_user.organisation_id)
    if not include_inactive:
        query = query.filter(ProductionLine.is_active.is_(True))
    query = apply_keyword_filter(query, q, ProductionLine.name, ProductionLine.code)
    query = apply_sort(query, sort_by, sort_direction, _SORT_FIELDS, default=ProductionLine.id)

    lines, pagination = paginate(query, page, page_size)
    return PaginatedResponse(data=[ProductionLineOut.model_validate(line) for line in lines], pagination=pagination)


@router.get("/{production_line_id}", response_model=ProductionLineOut)
def get_production_line(
    production_line_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> ProductionLine:
    return _get_production_line_in_org(db, production_line_id, current_user.organisation_id)


@router.post("", response_model=ProductionLineOut, status_code=status.HTTP_201_CREATED)
def create_production_line(
    payload: ProductionLineCreateRequest,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> ProductionLine:
    """Admin-gated, same shape as every other master-data mutation. No
    singleton constraint is enforced -- ordinary CRUD already produces
    "exactly one" today; see app/models/production_line.py's docstring."""
    production_line = ProductionLine(organisation_id=admin.organisation_id, code=payload.code, name=payload.name)
    db.add(production_line)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("A production line with this code or name already exists.") from exc

    audit_service.log_event(
        db,
        action=PRODUCTION_LINE_CREATED,
        module=MASTER_DATA_MODULE,
        organisation_id=admin.organisation_id,
        actor_user_id=admin.id,
        entity_type="production_line",
        entity_id=production_line.id,
        result="success",
        details=f"code: {production_line.code}, name: {production_line.name}",
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    db.refresh(production_line)
    return production_line


@router.patch("/{production_line_id}", response_model=ProductionLineOut)
def update_production_line(
    production_line_id: int,
    payload: ProductionLineUpdateRequest,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> ProductionLine:
    """Admin-gated partial update. `code` cannot be changed here -- see
    ProductionLineUpdateRequest. is_active has its own endpoint below."""
    production_line = _get_production_line_in_org(db, production_line_id, admin.organisation_id)

    updates = payload.model_dump(exclude_unset=True)
    before = {field: getattr(production_line, field) for field in updates}
    for field, value in updates.items():
        setattr(production_line, field, value)
    db.add(production_line)

    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("A production line with this name already exists.") from exc

    changes = audit_service.diff_fields(before, updates)
    if changes:
        audit_service.log_event(
            db,
            action=PRODUCTION_LINE_UPDATED,
            module=MASTER_DATA_MODULE,
            organisation_id=admin.organisation_id,
            actor_user_id=admin.id,
            entity_type="production_line",
            entity_id=production_line.id,
            result="success",
            details=audit_service.format_changes(changes),
            ip_address=request.client.host if request.client else None,
        )
    db.commit()
    db.refresh(production_line)
    return production_line


@router.patch("/{production_line_id}/status", response_model=ProductionLineOut)
def change_production_line_status(
    production_line_id: int,
    payload: ProductionLineStatusChangeRequest,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> ProductionLine:
    """Admin-gated activate/deactivate. No delete guard is needed yet --
    nothing in jdk_erp references `production_lines` besides Machine
    itself, and Machine's own FK validation already rejects an inactive
    line for new/updated machines (see app/api/machines.py)."""
    production_line = _get_production_line_in_org(db, production_line_id, admin.organisation_id)
    production_line.is_active = payload.is_active
    db.add(production_line)

    audit_service.log_event(
        db,
        action=PRODUCTION_LINE_STATUS_CHANGED,
        module=MASTER_DATA_MODULE,
        organisation_id=admin.organisation_id,
        actor_user_id=admin.id,
        entity_type="production_line",
        entity_id=production_line.id,
        result="success",
        details=f"is_active: {payload.is_active}",
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    db.refresh(production_line)
    return production_line
