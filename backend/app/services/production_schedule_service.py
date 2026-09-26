"""Production Scheduling (P4): when an accepted Production Plan will be
produced. Scheduling only -- no inventory, no Production Order, no change
to Sales Orders, Production Requirements or MRP demand.

Rules:
- only a `planned` Production Plan is scheduled; it may be split across
  several entries/days, and its active entries never total more than its
  planned quantity (no over-plan action exists, and the plan quantity is
  never raised here);
- an entry sits on a working day of the existing calendar
  (working_calendar_service: Sunday-Thursday, organisation holidays) on
  one machine -- the single active machine by default -- in a sequence
  unique among that machine's active entries that day;
- the required-by date (the Sales Order's for customer plans, the plan's
  own for independent ones) is never moved; an entry after it is late;
- daily capacity = machine capacity_quantity x production hours per day /
  capacity_period_hours, in the machine's capacity unit (the hours are the
  organisation's setting; unset -> capacity not configured). Each entry's
  quantity is converted to that unit with the existing uom_conversion
  (none -> the load cannot be stated, flagged). Overload is shown, never
  rearranged.
Callers audit and commit."""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.models.machine import Machine
from app.models.organisation import Organisation
from app.models.production_plan import CUSTOMER_DEMAND, PLAN_PLANNED, ProductionPlan
from app.models.production_schedule import SCHEDULE_CANCELLED, SCHEDULED, ProductionScheduleEntry
from app.models.product import Product
from app.models.unit import UnitOfMeasure
from app.services import production_order_service, uom_conversion, working_calendar_service

_ZERO = Decimal("0")
_Q = Decimal("0.0001")


def _plain(value) -> str:
    return format(Decimal(value).normalize(), "f")


def required_by(plan: ProductionPlan) -> date | None:
    """Demand information: the Sales Order's date for customer demand, the
    plan's own for independent production. Read, never moved."""
    if plan.source_type == CUSTOMER_DEMAND:
        return plan.requirement.required_by_date if plan.requirement is not None else None
    return plan.required_by_date


def _machine(db: Session, organisation_id: int, machine_id: int | None) -> Machine:
    if machine_id is not None:
        machine = db.query(Machine).filter(Machine.id == machine_id, Machine.organisation_id == organisation_id).first()
        if machine is None or not machine.is_active:
            raise ValidationError("Choose an active machine.", fields={"machine_id": "Invalid machine."})
        return machine
    machines = db.query(Machine).filter(Machine.organisation_id == organisation_id, Machine.is_active.is_(True)).all()
    if not machines:
        raise ValidationError("No active machine: add the production line's machine under Master Data first.", fields={"machine_id": "Required."})
    if len(machines) > 1:
        raise ValidationError("More than one active machine: choose one.", fields={"machine_id": "Required."})
    return machines[0]


def daily_capacity(db: Session, machine: Machine) -> tuple[Decimal | None, str | None]:
    """(capacity per working day in the machine's capacity unit, or None,
    and why not)."""
    hours = db.query(Organisation.production_hours_per_day).filter(Organisation.id == machine.organisation_id).scalar()
    if hours is None:
        return None, "Production hours per working day are not configured."
    if not machine.capacity_period_hours:
        return None, "The machine has no capacity period."
    capacity = machine.capacity_quantity * Decimal(hours) / machine.capacity_period_hours
    return capacity.quantize(_Q, rounding=ROUND_HALF_UP), None


def _in_capacity_unit(db: Session, quantity: Decimal, unit_id: int, capacity_unit_id: int) -> Decimal | None:
    if unit_id == capacity_unit_id:
        return quantity
    source, target = db.get(UnitOfMeasure, unit_id), db.get(UnitOfMeasure, capacity_unit_id)
    ratio = uom_conversion.resolve_conversion_ratio(source, target) if source and target else None
    return None if ratio is None else (quantity * ratio).quantize(_Q, rounding=ROUND_HALF_UP)


def _check_working_day(db: Session, organisation_id: int, day: date) -> None:
    holidays = working_calendar_service.get_holiday_dates(db, organisation_id, day, day)
    if not working_calendar_service.is_working_day(day, holidays):
        raise ValidationError(
            f"{day.isoformat()} is not a working day (Friday/Saturday or a holiday).", fields={"scheduled_date": "Not a working day."}
        )


def _active_entries(db: Session, plan_id: int) -> list[ProductionScheduleEntry]:
    return (
        db.query(ProductionScheduleEntry)
        .filter(ProductionScheduleEntry.production_plan_id == plan_id, ProductionScheduleEntry.status == SCHEDULED)
        .all()
    )


def scheduled_quantity(db: Session, plan_id: int) -> Decimal:
    return sum((e.quantity for e in _active_entries(db, plan_id)), _ZERO)


def _sequence(db: Session, machine_id: int, day: date, wanted: int | None, exclude_id: int | None = None) -> int:
    query = db.query(ProductionScheduleEntry.sequence).filter(
        ProductionScheduleEntry.machine_id == machine_id,
        ProductionScheduleEntry.scheduled_date == day,
        ProductionScheduleEntry.status == SCHEDULED,
    )
    if exclude_id is not None:
        query = query.filter(ProductionScheduleEntry.id != exclude_id)
    taken = {row[0] for row in query}
    if wanted is None:
        return max(taken, default=0) + 1
    if wanted < 1:
        raise ValidationError("Sequence starts at 1.", fields={"sequence": "Must be 1 or more."})
    if wanted in taken:
        raise ConflictError(f"Sequence {wanted} is already used on {day.isoformat()} for this machine.")
    return wanted


def _has_orders(db: Session, **filters) -> bool:
    return production_order_service.has_active_orders(db, **filters)


def _locked_plan(db: Session, plan_id: int, organisation_id: int) -> ProductionPlan:
    plan = (
        db.query(ProductionPlan)
        .filter(ProductionPlan.id == plan_id, ProductionPlan.organisation_id == organisation_id)
        .with_for_update()
        .first()
    )
    if plan is None:
        raise NotFoundError("Production plan not found.")
    return plan


def schedule(
    db: Session, organisation_id: int, plan_id: int, day: date, quantity: Decimal, machine_id: int | None, sequence: int | None, user_id: int
) -> ProductionScheduleEntry:
    plan = _locked_plan(db, plan_id, organisation_id)
    if plan.status != PLAN_PLANNED:
        raise ConflictError(f"Only an accepted (planned) Production Plan can be scheduled (this one is {plan.status}).")
    if quantity is None or quantity <= _ZERO:
        raise ValidationError("Schedule a positive quantity.", fields={"quantity": "Must be greater than zero."})
    remaining = plan.planned_quantity - scheduled_quantity(db, plan.id)
    if quantity > remaining:
        raise ConflictError(f"Only {_plain(max(remaining, _ZERO))} of this plan is still unscheduled; nothing was scheduled.")
    _check_working_day(db, organisation_id, day)
    machine = _machine(db, organisation_id, machine_id)
    entry = ProductionScheduleEntry(
        organisation_id=organisation_id,
        production_plan_id=plan.id,
        machine_id=machine.id,
        scheduled_date=day,
        sequence=_sequence(db, machine.id, day, sequence),
        quantity=quantity,
        status=SCHEDULED,
        daily_capacity_snapshot=daily_capacity(db, machine)[0],
        created_by_user_id=user_id,
    )
    db.add(entry)
    db.flush()
    return entry


def get_entry(db: Session, organisation_id: int, entry_id: int) -> ProductionScheduleEntry:
    entry = (
        db.query(ProductionScheduleEntry)
        .filter(ProductionScheduleEntry.id == entry_id, ProductionScheduleEntry.organisation_id == organisation_id)
        .first()
    )
    if entry is None:
        raise NotFoundError("Schedule entry not found.")
    return entry


def change(
    db: Session, entry: ProductionScheduleEntry, day: date | None, quantity: Decimal | None, sequence: int | None
) -> list[str]:
    """Move to another working day, change the quantity or the sequence.
    Returns the changes ("field: old -> new"); the plan, its demand and the
    required-by date are untouched."""
    plan = _locked_plan(db, entry.production_plan_id, entry.organisation_id)
    if entry.status != SCHEDULED:
        raise ConflictError("A cancelled schedule entry cannot be changed.")
    if _has_orders(db, entry_id=entry.id):
        raise ConflictError("This entry has a Production Order; cancel the order first to change the schedule.")
    if plan.status != PLAN_PLANNED:
        raise ConflictError(f"Its Production Plan is {plan.status}; the entry cannot be changed.")
    changes = []
    if quantity is not None and quantity != entry.quantity:
        if quantity <= _ZERO:
            raise ValidationError("Schedule a positive quantity.", fields={"quantity": "Must be greater than zero."})
        remaining = plan.planned_quantity - scheduled_quantity(db, plan.id) + entry.quantity
        if quantity > remaining:
            raise ConflictError(f"At most {_plain(remaining)} can be scheduled on this entry; nothing was changed.")
        changes.append(f"quantity: {_plain(entry.quantity)} -> {_plain(quantity)}")
        entry.quantity = quantity
    target_day = day if day is not None else entry.scheduled_date
    if day is not None and day != entry.scheduled_date:
        _check_working_day(db, entry.organisation_id, day)
        changes.append(f"scheduled_date: {entry.scheduled_date.isoformat()} -> {day.isoformat()}")
    if target_day != entry.scheduled_date or (sequence is not None and sequence != entry.sequence):
        new_sequence = _sequence(db, entry.machine_id, target_day, sequence if sequence is not None else None, exclude_id=entry.id)
        if new_sequence != entry.sequence:
            changes.append(f"sequence: {entry.sequence} -> {new_sequence}")
        entry.sequence = new_sequence
        entry.scheduled_date = target_day
    if changes:
        machine = db.get(Machine, entry.machine_id)
        entry.daily_capacity_snapshot = daily_capacity(db, machine)[0]
    db.flush()
    return changes


def cancel(db: Session, entry: ProductionScheduleEntry, reason: str) -> None:
    """The entry only -- never its plan or demand."""
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError("Say why the schedule entry is cancelled.", fields={"reason": "Required."})
    if entry.status != SCHEDULED:
        raise ConflictError("This schedule entry is already cancelled.")
    if _has_orders(db, entry_id=entry.id):
        raise ConflictError("This entry has a Production Order; cancel the order first.")
    entry.status = SCHEDULE_CANCELLED
    entry.cancelled_at = datetime.utcnow()
    entry.cancellation_reason = reason
    db.flush()


def cancel_for_plan(db: Session, plan: ProductionPlan, reason: str) -> list[ProductionScheduleEntry]:
    """A cancelled plan leaves no executable schedule behind. Refused while
    the plan still has an active Production Order (cancel that first)."""
    if _has_orders(db, plan_id=plan.id):
        raise ConflictError("This plan has an active Production Order; cancel the order first.")
    entries = _active_entries(db, plan.id)
    for entry in entries:
        entry.status = SCHEDULE_CANCELLED
        entry.cancelled_at = datetime.utcnow()
        entry.cancellation_reason = f"Production Plan cancelled: {reason}"
    db.flush()
    return entries


# --- Views ------------------------------------------------------------------------


@dataclass
class EntryView:
    id: int
    production_plan_id: int
    machine_id: int
    scheduled_date: date
    sequence: int
    product_id: int
    product_name: str
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


@dataclass
class MachineDay:
    machine_id: int
    machine_name: str
    capacity_quantity: Decimal | None
    capacity_unit_of_measure_id: int
    capacity_note: str | None
    scheduled_load: Decimal | None  # in the capacity unit; None if an entry cannot be converted
    remaining_capacity: Decimal | None
    overload_quantity: Decimal | None
    entries: list[EntryView] = field(default_factory=list)


@dataclass
class DayView:
    date: date
    is_working_day: bool
    machines: list[MachineDay] = field(default_factory=list)


def entry_view(db: Session, entry: ProductionScheduleEntry) -> EntryView:
    plan = entry.plan
    requirement = plan.requirement
    order = requirement.sales_order if requirement is not None else None
    due = required_by(plan)
    return EntryView(
        id=entry.id,
        production_plan_id=plan.id,
        machine_id=entry.machine_id,
        scheduled_date=entry.scheduled_date,
        sequence=entry.sequence,
        product_id=plan.product_id,
        product_name=db.query(Product.name).filter(Product.id == plan.product_id).scalar(),
        quantity=entry.quantity,
        unit_of_measure_id=plan.unit_of_measure_id,
        status=entry.status,
        source_type=plan.source_type,
        production_requirement_id=plan.production_requirement_id,
        sales_order_id=order.id if order is not None else None,
        sales_order_number=order.order_number if order is not None else None,
        required_by_date=due,
        late=due is not None and entry.scheduled_date > due,
        cancellation_reason=entry.cancellation_reason,
    )


def _machine_day(db: Session, machine: Machine, entries: list[ProductionScheduleEntry]) -> MachineDay:
    capacity, note = daily_capacity(db, machine)
    load: Decimal | None = _ZERO
    for entry in entries:
        converted = _in_capacity_unit(db, entry.quantity, entry.plan.unit_of_measure_id, machine.capacity_unit_of_measure_id)
        if converted is None:
            load = None
            note = "An entry's unit cannot be converted to the machine's capacity unit."
            break
        load += converted
    remaining = overload = None
    if capacity is not None and load is not None:
        remaining = max(capacity - load, _ZERO)
        overload = max(load - capacity, _ZERO)
    return MachineDay(
        machine_id=machine.id,
        machine_name=machine.name,
        capacity_quantity=capacity,
        capacity_unit_of_measure_id=machine.capacity_unit_of_measure_id,
        capacity_note=note,
        scheduled_load=load,
        remaining_capacity=remaining,
        overload_quantity=overload,
        entries=sorted((entry_view(db, e) for e in entries), key=lambda v: v.sequence),
    )


def days(db: Session, organisation_id: int, start: date, end: date) -> list[DayView]:
    """Each date in [start, end]: whether it is a working day and, per
    active machine (or any machine with entries that day), the scheduled
    entries in sequence with capacity, load, remaining and overload."""
    if end < start or (end - start).days > 62:
        raise ValidationError("Choose a range of up to 62 days.", fields={"end": "Invalid range."})
    holidays = working_calendar_service.get_holiday_dates(db, organisation_id, start, end)
    entries = (
        db.query(ProductionScheduleEntry)
        .filter(
            ProductionScheduleEntry.organisation_id == organisation_id,
            ProductionScheduleEntry.status == SCHEDULED,
            ProductionScheduleEntry.scheduled_date >= start,
            ProductionScheduleEntry.scheduled_date <= end,
        )
        .all()
    )
    machines = {m.id: m for m in db.query(Machine).filter(Machine.organisation_id == organisation_id, Machine.is_active.is_(True))}
    for entry in entries:
        machines.setdefault(entry.machine_id, db.get(Machine, entry.machine_id))
    result = []
    day = start
    while day <= end:
        view = DayView(date=day, is_working_day=working_calendar_service.is_working_day(day, holidays))
        for machine in sorted(machines.values(), key=lambda m: m.id):
            todays = [e for e in entries if e.scheduled_date == day and e.machine_id == machine.id]
            if view.is_working_day or todays:
                view.machines.append(_machine_day(db, machine, todays))
        result.append(view)
        day += timedelta(days=1)
    return result


@dataclass
class PlanScheduleView:
    production_plan_id: int
    product_id: int
    unit_of_measure_id: int
    status: str
    planned_quantity: Decimal
    scheduled_quantity: Decimal
    unscheduled_quantity: Decimal
    fully_scheduled: bool
    required_by_date: date | None
    entries: list[EntryView]
    overloaded_dates: list[date]
    exceptions: list[str]


def plan_view(db: Session, plan: ProductionPlan) -> PlanScheduleView:
    entries = (
        db.query(ProductionScheduleEntry)
        .filter(ProductionScheduleEntry.production_plan_id == plan.id)
        .order_by(ProductionScheduleEntry.scheduled_date, ProductionScheduleEntry.sequence, ProductionScheduleEntry.id)
        .all()
    )
    active = [e for e in entries if e.status == SCHEDULED]
    scheduled = sum((e.quantity for e in active), _ZERO)
    views = [entry_view(db, e) for e in entries]
    overloaded = []
    for key in sorted({(e.scheduled_date, e.machine_id) for e in active}):
        same_day = (
            db.query(ProductionScheduleEntry)
            .filter(
                ProductionScheduleEntry.machine_id == key[1],
                ProductionScheduleEntry.scheduled_date == key[0],
                ProductionScheduleEntry.status == SCHEDULED,
            )
            .all()
        )
        day = _machine_day(db, db.get(Machine, key[1]), same_day)
        if day.overload_quantity is not None and day.overload_quantity > _ZERO:
            overloaded.append(key[0])
    exceptions = []
    if any(v.late for v in views if v.status == SCHEDULED):
        exceptions.append("late")
    if overloaded:
        exceptions.append("capacity_overload")
    if plan.status == PLAN_PLANNED and scheduled < plan.planned_quantity:
        exceptions.append("not_fully_scheduled")
    return PlanScheduleView(
        production_plan_id=plan.id,
        product_id=plan.product_id,
        unit_of_measure_id=plan.unit_of_measure_id,
        status=plan.status,
        planned_quantity=plan.planned_quantity,
        scheduled_quantity=scheduled,
        unscheduled_quantity=max(plan.planned_quantity - scheduled, _ZERO),
        fully_scheduled=scheduled >= plan.planned_quantity,
        required_by_date=required_by(plan),
        entries=views,
        overloaded_dates=overloaded,
        exceptions=exceptions,
    )

