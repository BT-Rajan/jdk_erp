"""Production Orders (P5): production work formally issued to the factory.
No inventory effect of any kind -- creating, editing, issuing or
cancelling an order never touches stock, movements or allocation.

- create_draft: from one scheduled entry of a planned Production Plan;
  quantity defaults to what the entry still has without an order; the
  product and unit are the plan's, the machine and date the entry's.
- update_draft: quantity / notes, draft only.
- issue: re-validates everything (plan planned, entry scheduled and still
  covering the quantity, product active in its own unit, machine active,
  a BOM basis whose components are positive and still in their raw
  materials' own units), takes the entry's current date/machine, and
  snapshots the plan's BOM basis with each component's requirement for
  this quantity (bom_service.required_quantity) -- never re-resolving the
  current BOM, never converting units. Nothing is corrected silently.
- cancel: with a reason (history kept) -- draft, or issued / in progress
  before any production has been recorded; never afterwards.
Callers audit and commit."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.timezone import now_jdk
from app.models.machine import Machine
from app.models.product import Product
from app.models.production_order import (
    ORDER_ACTIVE,
    ORDER_CANCELLED,
    ORDER_DRAFT,
    ORDER_IN_PROGRESS,
    ORDER_ISSUED,
    ProductionOrder,
    ProductionOrderComponent,
)
from app.models.production_plan import PLAN_PLANNED, ProductionPlan
from app.models.production_schedule import SCHEDULED, ProductionScheduleEntry
from app.models.raw_material import RawMaterial
from app.services import bom_service, document_numbering, production_execution_service

_ZERO = Decimal("0")


def _plain(value) -> str:
    return format(Decimal(value).normalize(), "f")


def ordered_on_entry(db: Session, entry_id: int, exclude_id: int | None = None) -> Decimal:
    query = db.query(ProductionOrder).filter(
        ProductionOrder.production_schedule_entry_id == entry_id, ProductionOrder.status.in_(ORDER_ACTIVE)
    )
    if exclude_id is not None:
        query = query.filter(ProductionOrder.id != exclude_id)
    return sum((o.quantity for o in query), _ZERO)


def has_active_orders(db: Session, *, entry_id: int | None = None, plan_id: int | None = None) -> bool:
    query = db.query(ProductionOrder.id).filter(ProductionOrder.status.in_(ORDER_ACTIVE))
    if entry_id is not None:
        query = query.filter(ProductionOrder.production_schedule_entry_id == entry_id)
    if plan_id is not None:
        query = query.filter(ProductionOrder.production_plan_id == plan_id)
    return query.first() is not None


def _locked_entry(db: Session, organisation_id: int, entry_id: int) -> ProductionScheduleEntry:
    entry = (
        db.query(ProductionScheduleEntry)
        .filter(ProductionScheduleEntry.id == entry_id, ProductionScheduleEntry.organisation_id == organisation_id)
        .with_for_update()
        .first()
    )
    if entry is None:
        raise NotFoundError("Schedule entry not found.")
    return entry


def _check_source(db: Session, entry: ProductionScheduleEntry) -> ProductionPlan:
    if entry.status != SCHEDULED:
        raise ConflictError("Its schedule entry is cancelled; nothing can be issued from it.")
    plan = db.get(ProductionPlan, entry.production_plan_id)
    if plan is None or plan.status != PLAN_PLANNED:
        raise ConflictError(f"Its Production Plan is {plan.status if plan else 'missing'}; nothing can be issued from it.")
    return plan


def _check_quantity(db: Session, entry: ProductionScheduleEntry, quantity: Decimal | None, exclude_id: int | None) -> Decimal:
    if quantity is None or quantity <= _ZERO:
        raise ValidationError("Enter a positive production quantity.", fields={"quantity": "Must be greater than zero."})
    available = entry.quantity - ordered_on_entry(db, entry.id, exclude_id)
    if quantity > available:
        raise ConflictError(f"Only {_plain(max(available, _ZERO))} of this schedule entry is not yet on a Production Order.")
    return quantity


def create_draft(db: Session, organisation_id: int, entry_id: int, quantity: Decimal | None, notes: str | None, user_id: int) -> ProductionOrder:
    entry = _locked_entry(db, organisation_id, entry_id)
    plan = _check_source(db, entry)
    if quantity is None:
        quantity = entry.quantity - ordered_on_entry(db, entry.id)
    quantity = _check_quantity(db, entry, quantity, None)

    def build(number: str) -> ProductionOrder:
        return ProductionOrder(
            organisation_id=organisation_id,
            order_number=number,
            production_plan_id=plan.id,
            production_schedule_entry_id=entry.id,
            product_id=plan.product_id,
            unit_of_measure_id=plan.unit_of_measure_id,
            quantity=quantity,
            machine_id=entry.machine_id,
            scheduled_date=entry.scheduled_date,
            status=ORDER_DRAFT,
            notes=(notes or "").strip() or None,
            created_by_user_id=user_id,
        )

    return document_numbering.insert_with_yearly_number(
        db,
        build=build,
        number_column=ProductionOrder.order_number,
        organisation_column=ProductionOrder.organisation_id,
        organisation_id=organisation_id,
        type_digit=document_numbering.PRODUCTION_ORDER_TYPE_DIGIT,
        today=now_jdk().date(),
        label="production order",
    )


def _locked(db: Session, order: ProductionOrder) -> ProductionOrder:
    return db.query(ProductionOrder).filter(ProductionOrder.id == order.id).with_for_update().one()


def update_draft(db: Session, order: ProductionOrder, updates: dict) -> list[str]:
    order = _locked(db, order)
    if order.status != ORDER_DRAFT:
        raise ConflictError(f"Only a draft Production Order can be edited (this one is {order.status}).")
    changes = []
    if "quantity" in updates:
        entry = _locked_entry(db, order.organisation_id, order.production_schedule_entry_id)
        quantity = _check_quantity(db, entry, updates["quantity"], order.id)
        if quantity != order.quantity:
            changes.append(f"quantity: {_plain(order.quantity)} -> {_plain(quantity)}")
            order.quantity = quantity
    if "notes" in updates:
        notes = (updates["notes"] or "").strip() or None
        if notes != order.notes:
            changes.append("notes changed")
            order.notes = notes
    db.flush()
    return changes


def issue(db: Session, order: ProductionOrder, user_id: int) -> None:
    order = _locked(db, order)
    if order.status != ORDER_DRAFT:
        raise ConflictError(f"Only a draft Production Order can be issued (this one is {order.status}).")
    entry = _locked_entry(db, order.organisation_id, order.production_schedule_entry_id)
    plan = _check_source(db, entry)
    if entry.production_plan_id != order.production_plan_id or plan.product_id != order.product_id:
        raise ConflictError("The Production Order no longer matches its plan and schedule.")
    _check_quantity(db, entry, order.quantity, order.id)
    product = db.get(Product, order.product_id)
    if product is None or not product.is_active:
        raise ConflictError("The product is not active.")
    if product.unit_of_measure_id != order.unit_of_measure_id or plan.unit_of_measure_id != order.unit_of_measure_id:
        raise ConflictError("The product's production unit no longer matches the order; nothing is converted.")
    machine = db.get(Machine, entry.machine_id)
    if machine is None or not machine.is_active:
        raise ConflictError("The scheduled machine is not active.")
    if plan.bom_id is None or not plan.bom_base_quantity or plan.bom_base_quantity <= _ZERO or not plan.components:
        raise ConflictError("BOM required: the plan has no valid BOM basis, so the raw materials are unknown.")
    components = []
    for component in plan.components:
        material = db.get(RawMaterial, component.raw_material_id)
        if component.quantity is None or component.quantity <= _ZERO:
            raise ConflictError(f"The BOM basis has a non-positive quantity for {material.name}.")
        if material.unit_of_measure_id != component.unit_of_measure_id:
            raise ConflictError(f"{material.name}'s unit has changed since the plan's BOM basis was taken; nothing is converted.")
        required = bom_service.required_quantity(component.quantity, order.quantity, plan.bom_base_quantity)
        if required <= _ZERO:
            raise ConflictError(f"The requirement for {material.name} rounds to zero for this quantity.")
        components.append(
            ProductionOrderComponent(
                raw_material_id=material.id,
                quantity=component.quantity,
                unit_of_measure_id=component.unit_of_measure_id,
                required_quantity=required,
            )
        )
    order.components = components
    order.bom_id, order.bom_base_quantity = plan.bom_id, plan.bom_base_quantity
    order.machine_id, order.scheduled_date = entry.machine_id, entry.scheduled_date
    order.status = ORDER_ISSUED
    order.issued_at = datetime.utcnow()
    order.issued_by_user_id = user_id
    db.flush()


def cancel(db: Session, order: ProductionOrder, reason: str) -> str:
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError("Say why the Production Order is cancelled.", fields={"reason": "Required."})
    order = _locked(db, order)
    if order.status == ORDER_CANCELLED:
        raise ConflictError("This Production Order is already cancelled.")
    # P6: once anything has been produced the order is history, not a
    # plan -- cancelling it would pretend production never happened.
    if order.status not in (ORDER_DRAFT, ORDER_ISSUED, ORDER_IN_PROGRESS) or production_execution_service.produced_quantity(db, order.id) > _ZERO:
        raise ConflictError("Production has already been recorded on this order; it cannot be cancelled.")
    previous = order.status
    order.status = ORDER_CANCELLED
    order.cancelled_at = datetime.utcnow()
    order.cancellation_reason = reason
    db.flush()
    return previous
