"""Production Scheduling (P4): when accepted Production Plans will be
produced.

- GET  /api/production-schedule/days?start=&end=: the daily schedule --
  per working day and machine, entries in sequence with product, plan,
  source, required-by, and capacity / load / remaining / overload;
- POST /api/production-schedule: schedule part (or all) of a planned plan;
- PATCH /api/production-schedule/{id}: move / change quantity / sequence;
- POST /api/production-schedule/{id}/cancel: cancel an entry (reason);
- GET  /api/production-plans/{id}/schedule: planned / scheduled /
  unscheduled, entries, late and capacity exceptions.

`production:view` reads, `production:manage` changes. Every change is
audited old -> new (module `production`). Nothing here moves inventory,
creates a Production Order or changes demand."""

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.errors import NotFoundError
from app.models.audit_event import PRODUCTION_MODULE, PRODUCTION_RESCHEDULED, PRODUCTION_SCHEDULE_CANCELLED, PRODUCTION_SCHEDULED
from app.models.production_plan import ProductionPlan
from app.models.production_schedule import ProductionScheduleEntry
from app.models.user import User
from app.services import audit_service, production_schedule_service, production_scope

router = APIRouter(tags=["production-schedule"])


class EntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    production_plan_id: int
    machine_id: int
    scheduled_date: date
    sequence: int
    product_id: int
    product_name: str | None
    quantity: Decimal
    unit_of_measure_id: int
    status: str
    source_type: str
    production_requirement_id: int | None
    sales_order_id: int | None
    sales_order_number: str | None
    required_by_date: date | None
    late: bool
    cancellation_reason: str | None


class MachineDayOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    machine_id: int
    machine_name: str
    capacity_quantity: Decimal | None
    capacity_unit_of_measure_id: int
    capacity_note: str | None
    scheduled_load: Decimal | None
    remaining_capacity: Decimal | None
    overload_quantity: Decimal | None
    entries: list[EntryOut]


class DayOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    date: date
    is_working_day: bool
    machines: list[MachineDayOut]


class PlanScheduleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    production_plan_id: int
    product_id: int
    unit_of_measure_id: int
    status: str
    planned_quantity: Decimal
    scheduled_quantity: Decimal
    unscheduled_quantity: Decimal
    fully_scheduled: bool
    required_by_date: date | None
    entries: list[EntryOut]
    overloaded_dates: list[date]
    exceptions: list[str]


class ScheduleRequest(BaseModel):
    production_plan_id: int
    scheduled_date: date
    quantity: Decimal = Field(gt=0, max_digits=14, decimal_places=4)
    machine_id: int | None = None
    sequence: int | None = Field(default=None, ge=1)


class RescheduleRequest(BaseModel):
    scheduled_date: date | None = None
    quantity: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=4)
    sequence: int | None = Field(default=None, ge=1)
    reason: str | None = Field(default=None, max_length=2000)


class CancelRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


def audit_entry(db: Session, request: Request, user: User, action: str, entry: ProductionScheduleEntry, details: str) -> None:
    audit_service.log_event(
        db,
        action=action,
        module=PRODUCTION_MODULE,
        organisation_id=user.organisation_id,
        actor_user_id=user.id,
        entity_type="production_schedule_entry",
        entity_id=entry.id,
        result="success",
        details=f"plan {entry.production_plan_id}, machine {entry.machine_id}; {details}",
        ip_address=request.client.host if request.client else None,
    )


def _entry_out(db: Session, entry_id: int, user: User) -> EntryOut:
    db.expire_all()
    entry = production_schedule_service.get_entry(db, user.organisation_id, entry_id)
    return EntryOut.model_validate(production_schedule_service.entry_view(db, entry))


@router.get("/api/production-schedule/days", response_model=list[DayOut])
def get_schedule_days(
    start: date = Query(...),
    end: date = Query(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[DayOut]:
    production_scope.require_permission(db, current_user, production_scope.VIEW)
    return [DayOut.model_validate(d) for d in production_schedule_service.days(db, current_user.organisation_id, start, end)]


@router.get("/api/production-plans/{plan_id}/schedule", response_model=PlanScheduleOut)
def get_plan_schedule(plan_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> PlanScheduleOut:
    production_scope.require_permission(db, current_user, production_scope.VIEW)
    plan = db.query(ProductionPlan).filter(ProductionPlan.id == plan_id, ProductionPlan.organisation_id == current_user.organisation_id).first()
    if plan is None:
        raise NotFoundError("Production plan not found.")
    return PlanScheduleOut.model_validate(production_schedule_service.plan_view(db, plan))


@router.post("/api/production-schedule", response_model=EntryOut, status_code=status.HTTP_201_CREATED)
def schedule_production(
    payload: ScheduleRequest, request: Request, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> EntryOut:
    production_scope.require_permission(db, current_user, production_scope.MANAGE)
    entry = production_schedule_service.schedule(
        db, current_user.organisation_id, payload.production_plan_id, payload.scheduled_date, payload.quantity,
        payload.machine_id, payload.sequence, current_user.id,
    )
    audit_entry(
        db, request, current_user, PRODUCTION_SCHEDULED, entry,
        f"{entry.scheduled_date.isoformat()} #{entry.sequence}: quantity {entry.quantity}",
    )
    db.commit()
    return _entry_out(db, entry.id, current_user)


@router.patch("/api/production-schedule/{entry_id}", response_model=EntryOut)
def reschedule_production(
    entry_id: int, payload: RescheduleRequest, request: Request, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> EntryOut:
    """Move / change; the previous values stay in the audit trail."""
    production_scope.require_permission(db, current_user, production_scope.MANAGE)
    entry = production_schedule_service.get_entry(db, current_user.organisation_id, entry_id)
    changes = production_schedule_service.change(db, entry, payload.scheduled_date, payload.quantity, payload.sequence)
    if changes:
        reason = (payload.reason or "").strip()
        audit_entry(db, request, current_user, PRODUCTION_RESCHEDULED, entry, "; ".join(changes) + (f"; reason: {reason}" if reason else ""))
    db.commit()
    return _entry_out(db, entry_id, current_user)


@router.post("/api/production-schedule/{entry_id}/cancel", response_model=EntryOut)
def cancel_schedule_entry(
    entry_id: int, payload: CancelRequest, request: Request, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> EntryOut:
    """The entry only: its Production Plan and demand stay as they are."""
    production_scope.require_permission(db, current_user, production_scope.MANAGE)
    entry = production_schedule_service.get_entry(db, current_user.organisation_id, entry_id)
    production_schedule_service.cancel(db, entry, payload.reason)
    audit_entry(db, request, current_user, PRODUCTION_SCHEDULE_CANCELLED, entry, f"scheduled -> cancelled; reason: {payload.reason.strip()}")
    db.commit()
    return _entry_out(db, entry_id, current_user)
