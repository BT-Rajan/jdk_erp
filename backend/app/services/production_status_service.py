"""Production Status (P7): "what is planned, what is happening, and what has
actually been produced?" -- read-only, derived entirely from existing
records: Production Orders (planned quantity, status, date, machine),
their schedule entries (sequence), posted Production Executions (produced
quantity -- never a stored copy), the plan/requirement trace, Raw Material
Inventory (availability) and the schedule's own day capacity (overload).
Nothing here writes anything; posting production is P6's
Record Production only.

Exceptions shown (existing data only, no new rules):
- `late`: scheduled after the required-by date (the schedule's own rule);
- `overdue`: the required-by date has passed and quantity remains;
- `not_produced`: the scheduled day has passed and quantity remains;
- `material_shortage`: raw material on hand is below what the remaining
  quantity needs, from the order's BOM snapshot;
- `schedule_overload`: the machine's day is over capacity (P4);
- `cancelled`."""

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.timezone import now_jdk
from app.models.machine import Machine
from app.models.product import Product
from app.models.production_line import ProductionLine
from app.models.production_order import (
    ORDER_CANCELLED,
    ORDER_COMPLETED,
    ORDER_DRAFT,
    ORDER_IN_PROGRESS,
    ORDER_ISSUED,
    ORDER_PARTIALLY_COMPLETED,
    ProductionOrder,
)
from app.models.production_schedule import SCHEDULED, ProductionScheduleEntry
from app.models.sales_order import SalesOrderLine
from app.services import (
    bom_service,
    inventory_service,
    production_execution_service,
    production_schedule_service,
    working_calendar_service,
)

_ZERO = Decimal("0")
_HORIZON = 31


def previous_working_day(db: Session, organisation_id: int, day: date) -> date:
    holidays = working_calendar_service.get_holiday_dates(db, organisation_id, day - timedelta(days=_HORIZON), day)
    candidate = day - timedelta(days=1)
    while not working_calendar_service.is_working_day(candidate, holidays) and (day - candidate).days < _HORIZON:
        candidate -= timedelta(days=1)
    return candidate


def next_working_day(db: Session, organisation_id: int, day: date) -> date:
    holidays = working_calendar_service.get_holiday_dates(db, organisation_id, day, day + timedelta(days=_HORIZON))
    return working_calendar_service.next_working_day(day, holidays)


@dataclass
class OrderStatusRow:
    production_order_id: int
    order_number: str
    sequence: int | None
    product_id: int
    product_name: str | None
    unit_of_measure_id: int
    planned_quantity: Decimal
    produced_quantity: Decimal
    remaining_quantity: Decimal
    status: str
    scheduled_date: date
    required_by_date: date | None
    production_line_name: str | None
    machine_name: str | None
    source_type: str
    sales_order_number: str | None
    sales_order_line_number: int | None
    production_plan_id: int
    exceptions: list[str] = field(default_factory=list)


def order_row(db: Session, order: ProductionOrder, today: date, overloaded: set[tuple[int, date]] | None = None) -> OrderStatusRow:
    plan = order.plan
    requirement = plan.requirement if plan is not None else None
    sales_order = requirement.sales_order if requirement is not None else None
    line = db.get(SalesOrderLine, requirement.sales_order_line_id) if requirement is not None else None
    machine = db.get(Machine, order.machine_id)
    production_line = db.get(ProductionLine, machine.production_line_id) if machine is not None else None
    entry = db.get(ProductionScheduleEntry, order.production_schedule_entry_id)
    produced = production_execution_service.produced_quantity(db, order.id)
    remaining = max(order.quantity - produced, _ZERO)
    due = production_schedule_service.required_by(plan) if plan is not None else None
    row = OrderStatusRow(
        production_order_id=order.id,
        order_number=order.order_number,
        sequence=entry.sequence if entry is not None else None,
        product_id=order.product_id,
        product_name=db.query(Product.name).filter(Product.id == order.product_id).scalar(),
        unit_of_measure_id=order.unit_of_measure_id,
        planned_quantity=order.quantity,
        produced_quantity=produced,
        remaining_quantity=remaining,
        status=order.status,
        scheduled_date=order.scheduled_date,
        required_by_date=due,
        production_line_name=production_line.name if production_line else None,
        machine_name=machine.name if machine else None,
        source_type=plan.source_type if plan is not None else "",
        sales_order_number=sales_order.order_number if sales_order is not None else None,
        sales_order_line_number=line.line_number if line is not None else None,
        production_plan_id=order.production_plan_id,
    )
    if order.status == ORDER_CANCELLED:
        row.exceptions.append("cancelled")
        return row
    open_quantity = remaining > _ZERO and order.status != ORDER_COMPLETED
    if due is not None and order.scheduled_date > due:
        row.exceptions.append("late")
    if open_quantity and due is not None and due < today:
        row.exceptions.append("overdue")
    if open_quantity and order.scheduled_date < today:
        row.exceptions.append("not_produced")
    if open_quantity and order.components and order.bom_base_quantity:
        for component in order.components:
            need = bom_service.required_quantity(component.quantity, remaining, order.bom_base_quantity)
            on_hand = inventory_service.get_organisation_quantity_on_hand(
                db, organisation_id=order.organisation_id, raw_material_id=component.raw_material_id
            )
            if on_hand < need:
                row.exceptions.append("material_shortage")
                break
    if overloaded is not None and (order.machine_id, order.scheduled_date) in overloaded:
        row.exceptions.append("schedule_overload")
    return row


@dataclass
class UnitTotals:
    unit_of_measure_id: int
    scheduled_quantity: Decimal = _ZERO
    produced_quantity: Decimal = _ZERO
    remaining_quantity: Decimal = _ZERO


@dataclass
class DayStatus:
    date: date
    is_working_day: bool
    previous_working_day: date
    next_working_day: date
    order_count: int
    completed_count: int
    in_progress_count: int  # in progress or partially completed
    not_started_count: int  # issued, nothing produced
    cancelled_count: int
    totals: list[UnitTotals]
    orders: list[OrderStatusRow]


def day_status(db: Session, organisation_id: int, day: date) -> DayStatus:
    """Every issued (or later) Production Order scheduled on `day`, in
    schedule sequence, with totals per production unit (quantities in
    different units are never added together). Cancelled orders are listed
    and counted apart; drafts are not issued work and are left out."""
    today = now_jdk().date()
    orders = (
        db.query(ProductionOrder)
        .filter(
            ProductionOrder.organisation_id == organisation_id,
            ProductionOrder.scheduled_date == day,
            ProductionOrder.status != ORDER_DRAFT,
        )
        .all()
    )
    overloaded = set()
    for machine_id in {o.machine_id for o in orders}:
        entries = (
            db.query(ProductionScheduleEntry)
            .filter(
                ProductionScheduleEntry.machine_id == machine_id,
                ProductionScheduleEntry.scheduled_date == day,
                ProductionScheduleEntry.status == SCHEDULED,
            )
            .all()
        )
        if entries:
            view = production_schedule_service.machine_day(db, db.get(Machine, machine_id), entries)
            if view.overload_quantity is not None and view.overload_quantity > _ZERO:
                overloaded.add((machine_id, day))
    rows = [order_row(db, o, today, overloaded) for o in orders]
    rows.sort(key=lambda r: (r.status == ORDER_CANCELLED, r.sequence or 0, r.order_number))
    totals: dict[int, UnitTotals] = {}
    for row in rows:
        if row.status == ORDER_CANCELLED:
            continue
        unit = totals.setdefault(row.unit_of_measure_id, UnitTotals(row.unit_of_measure_id))
        unit.scheduled_quantity += row.planned_quantity
        unit.produced_quantity += row.produced_quantity
        unit.remaining_quantity += row.remaining_quantity
    holidays = working_calendar_service.get_holiday_dates(db, organisation_id, day, day)
    active = [r for r in rows if r.status != ORDER_CANCELLED]
    return DayStatus(
        date=day,
        is_working_day=working_calendar_service.is_working_day(day, holidays),
        previous_working_day=previous_working_day(db, organisation_id, day),
        next_working_day=next_working_day(db, organisation_id, day),
        order_count=len(active),
        completed_count=sum(1 for r in active if r.status == ORDER_COMPLETED),
        in_progress_count=sum(1 for r in active if r.status in (ORDER_IN_PROGRESS, ORDER_PARTIALLY_COMPLETED)),
        not_started_count=sum(1 for r in active if r.status == ORDER_ISSUED),
        cancelled_count=len(rows) - len(active),
        totals=list(totals.values()),
        orders=rows,
    )
