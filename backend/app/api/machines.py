from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin
from app.core.database import get_db
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.list_query import apply_sort, paginate
from app.core.search import apply_keyword_filter
from app.models.audit_event import MASTER_DATA_MODULE, MACHINE_CREATED, MACHINE_STATUS_CHANGED, MACHINE_UPDATED
from app.models.machine import Machine
from app.models.production_line import ProductionLine
from app.models.unit import UnitOfMeasure
from app.models.user import User
from app.schemas.machine import (
    MachineCreateRequest,
    MachineOut,
    MachineStatusChangeRequest,
    MachineUpdateRequest,
)
from app.schemas.pagination import PaginatedResponse
from app.services import audit_service

router = APIRouter(prefix="/api/machines", tags=["machines"])

# See app/api/users.py's _SORT_FIELDS for the reasoning.
_SORT_FIELDS = {
    "code": Machine.code,
    "name": Machine.name,
    "created_at": Machine.created_at,
}


def _get_machine_in_org(db: Session, machine_id: int, organisation_id: int) -> Machine:
    machine = db.query(Machine).filter(Machine.id == machine_id, Machine.organisation_id == organisation_id).first()
    if machine is None:
        raise NotFoundError("Machine not found.")
    return machine


def _resolve_active_production_line(db: Session, production_line_id: int, organisation_id: int) -> ProductionLine:
    """A direct, all-in-one-filter query (not a reuse of
    get_production_line_in_org) so a missing, inactive, and
    cross-organisation production_line_id are all rejected the same way
    -- 422, not a 404 leaking whether the id exists at all -- matching
    Product/RawMaterial's category/unit FK validation exactly."""
    line = (
        db.query(ProductionLine)
        .filter(
            ProductionLine.id == production_line_id,
            ProductionLine.organisation_id == organisation_id,
            ProductionLine.is_active.is_(True),
        )
        .first()
    )
    if line is None:
        raise ValidationError(
            "production_line_id must be an active production line in your organisation.",
            fields={"production_line_id": "Not a valid active production line in your organisation."},
        )
    return line


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
            "capacity_unit_of_measure_id must be an active unit of measure in your organisation.",
            fields={"capacity_unit_of_measure_id": "Not a valid active unit of measure in your organisation."},
        )
    return unit


@router.get("", response_model=PaginatedResponse[MachineOut])
def list_machines(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    sort_by: str | None = Query(None),
    sort_direction: Literal["asc", "desc"] = Query("asc"),
    include_inactive: bool = Query(False),
    q: str | None = Query(None, max_length=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PaginatedResponse[MachineOut]:
    """Scoped to the caller's own organisation only. Open to any
    authenticated organisation member -- a future Feasibility/Production
    consumer (and anyone checking current capacity) needs to look this
    up; only mutations are admin-gated."""
    query = db.query(Machine).filter(Machine.organisation_id == current_user.organisation_id)
    if not include_inactive:
        query = query.filter(Machine.is_active.is_(True))
    query = apply_keyword_filter(query, q, Machine.name, Machine.code)
    query = apply_sort(query, sort_by, sort_direction, _SORT_FIELDS, default=Machine.id)

    machines, pagination = paginate(query, page, page_size)
    return PaginatedResponse(data=[MachineOut.model_validate(m) for m in machines], pagination=pagination)


@router.get("/{machine_id}", response_model=MachineOut)
def get_machine(machine_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Machine:
    return _get_machine_in_org(db, machine_id, current_user.organisation_id)


@router.post("", response_model=MachineOut, status_code=status.HTTP_201_CREATED)
def create_machine(
    payload: MachineCreateRequest,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Machine:
    """Admin-gated. `code` is caller-supplied and required, with no
    update path (see MachineUpdateRequest)."""
    _resolve_active_production_line(db, payload.production_line_id, admin.organisation_id)
    _resolve_active_unit(db, payload.capacity_unit_of_measure_id, admin.organisation_id)

    machine = Machine(
        organisation_id=admin.organisation_id,
        code=payload.code,
        name=payload.name,
        production_line_id=payload.production_line_id,
        capacity_quantity=payload.capacity_quantity,
        capacity_unit_of_measure_id=payload.capacity_unit_of_measure_id,
        capacity_period_hours=payload.capacity_period_hours,
    )
    db.add(machine)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("A machine with this code or name already exists.") from exc

    audit_service.log_event(
        db,
        action=MACHINE_CREATED,
        module=MASTER_DATA_MODULE,
        organisation_id=admin.organisation_id,
        actor_user_id=admin.id,
        entity_type="machine",
        entity_id=machine.id,
        result="success",
        details=f"code: {machine.code}, name: {machine.name}, capacity: {machine.capacity_quantity}/{machine.capacity_period_hours}h",
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    db.refresh(machine)
    return machine


@router.patch("/{machine_id}", response_model=MachineOut)
def update_machine(
    machine_id: int,
    payload: MachineUpdateRequest,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Machine:
    """Admin-gated partial update -- this is how an authorised user
    reconfigures production capacity (e.g. 2 -> 2.5 tonnes/hour) without
    any code change (docs/modules/machines.md #4). `code` cannot be
    changed here. is_active has its own endpoint below."""
    machine = _get_machine_in_org(db, machine_id, admin.organisation_id)

    updates = payload.model_dump(exclude_unset=True)
    if "production_line_id" in updates:
        _resolve_active_production_line(db, updates["production_line_id"], admin.organisation_id)
    if "capacity_unit_of_measure_id" in updates:
        _resolve_active_unit(db, updates["capacity_unit_of_measure_id"], admin.organisation_id)

    before = {field: getattr(machine, field) for field in updates}
    for field, value in updates.items():
        setattr(machine, field, value)
    db.add(machine)

    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("A machine with this name already exists.") from exc

    changes = audit_service.diff_fields(before, updates)
    if changes:
        audit_service.log_event(
            db,
            action=MACHINE_UPDATED,
            module=MASTER_DATA_MODULE,
            organisation_id=admin.organisation_id,
            actor_user_id=admin.id,
            entity_type="machine",
            entity_id=machine.id,
            result="success",
            details=audit_service.format_changes(changes),
            ip_address=request.client.host if request.client else None,
        )
    db.commit()
    db.refresh(machine)
    return machine


@router.patch("/{machine_id}/status", response_model=MachineOut)
def change_machine_status(
    machine_id: int,
    payload: MachineStatusChangeRequest,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Machine:
    """Admin-gated activate/deactivate. No delete guard is needed yet --
    nothing in jdk_erp references `machines` (Feasibility/Production
    Scheduling are unbuilt). Deactivating the only machine has no
    operational effect from this module alone (docs/modules/machines.md
    #11) -- whichever future Production module schedules against a
    machine is responsible for rejecting an inactive one at scheduling
    time, the same rule already established for every other master's
    is_active flag."""
    machine = _get_machine_in_org(db, machine_id, admin.organisation_id)
    machine.is_active = payload.is_active
    db.add(machine)

    audit_service.log_event(
        db,
        action=MACHINE_STATUS_CHANGED,
        module=MASTER_DATA_MODULE,
        organisation_id=admin.organisation_id,
        actor_user_id=admin.id,
        entity_type="machine",
        entity_id=machine.id,
        result="success",
        details=f"is_active: {payload.is_active}",
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    db.refresh(machine)
    return machine
