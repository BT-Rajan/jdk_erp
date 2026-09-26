"""Turns a handed-off Sales Order into its fulfilment result and
production demand (Sales S15.2, per the S15.1 decisions).

For each line, in line order and independently of the others:
- Finished Goods first: the product's *free* FG -- physical on hand less
  every open allocation, including earlier lines of this same order
  (fg_allocation_service) -- is allocated to the line up to its quantity
  (the S15.1 rule: allocation starts at hand-off), so the same stock is
  never counted for two orders;
- the covered (allocated) part is recorded; any remainder becomes one
  Production Requirement for that line, in the product's own unit;
- the requirement snapshots the product's active BOM (base quantity and
  components, each in its raw material's own unit at that moment); with
  no active BOM it is recorded as `bom_required`, without a snapshot.

A line whose unit is not the product's stock unit is refused: FG stock
and the BOM base are both in that unit, and nothing is converted here.

Nothing is moved or issued (allocation is a claim, not a movement);
nothing is scheduled, planned or produced; the Sales Order is never
changed.

Lifecycle -- a requirement is a demand/reference record (the part of an
order line not covered by delivered or allocated FG), never a production
command:
- recalculate_line: after every allocation, release, delivery or
  confirmed quantity change, in the same transaction, the requirement
  follows ordered - delivered - allocated (`open`/`bom_required` with
  that quantity, or `satisfied` at zero);
- snapshot_bom: `bom_required` -> `open` once the product has an active
  BOM; the quantity is untouched and the snapshot is never refreshed;
- cancel_for_order: the order's active requirements -> `cancelled` when
  the Sales Order is cancelled; final.
Callers audit and commit."""

from decimal import Decimal

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.errors import ConflictError, ValidationError
from app.models.bom import ACTIVE, Bom, BomComponent
from app.models.product import Product
from app.models.production_requirement import (
    FROM_STOCK,
    PRODUCTION_REQUIRED,
    REQUIREMENT_ACTIVE,
    REQUIREMENT_BOM_REQUIRED,
    REQUIREMENT_CANCELLED,
    REQUIREMENT_SATISFIED,
    REQUIREMENT_OPEN,
    ProductionRequirement,
    ProductionRequirementComponent,
    SalesOrderLineFulfilment,
)
from app.models.raw_material import RawMaterial
from app.models.sales_order import CANCELLED, HANDED_OFF, SalesOrder, SalesOrderLine
from app.services import fg_allocation_service

_ZERO = Decimal("0")


def _snapshot_bom(db: Session, requirement: ProductionRequirement) -> None:
    bom = (
        db.query(Bom)
        .filter(Bom.organisation_id == requirement.organisation_id, Bom.product_id == requirement.product_id, Bom.status == ACTIVE)
        .first()
    )
    if bom is None:
        requirement.status = REQUIREMENT_BOM_REQUIRED
        return
    requirement.status = REQUIREMENT_OPEN
    requirement.bom_id = bom.id
    requirement.bom_base_quantity = bom.base_quantity
    components = db.query(BomComponent).filter(BomComponent.bom_id == bom.id).order_by(BomComponent.id).all()
    for component in components:
        material = db.get(RawMaterial, component.raw_material_id)
        requirement.components.append(
            ProductionRequirementComponent(
                raw_material_id=component.raw_material_id,
                quantity=component.quantity,
                unit_of_measure_id=material.unit_of_measure_id,
            )
        )


def create_for_order(db: Session, order: SalesOrder) -> list[SalesOrderLineFulfilment]:
    """Assesses every line of a handed-off order once and records the
    result, plus a Production Requirement for each shortfall. The caller
    audits and commits. Refused for an order that is not handed off, or
    one already assessed."""
    if order.status != HANDED_OFF:
        raise ConflictError(f"Only a handed-off Sales Order has production demand (this one is {order.status}).")
    line_ids = [line.id for line in order.lines]
    if db.query(SalesOrderLineFulfilment.id).filter(SalesOrderLineFulfilment.sales_order_line_id.in_(line_ids)).first():
        raise ConflictError("This Sales Order's fulfilment has already been assessed.")

    results: list[SalesOrderLineFulfilment] = []
    for line in order.lines:
        product = db.get(Product, line.product_id)
        if product is None or line.unit_of_measure_id != product.unit_of_measure_id:
            raise ValidationError(
                f"Line {line.line_number} is not in its product's stock unit; nothing is converted.",
                fields={"lines": f"Line {line.line_number}: unit does not match the product's unit."},
            )
        if line.quantity is None or line.quantity <= _ZERO:
            raise ValidationError(f"Line {line.line_number} has no positive quantity.", fields={"lines": "Quantity must be positive."})
        available, covered = fg_allocation_service.allocate_free_up_to(db, order, line, line.quantity)
        shortfall = line.quantity - covered

        fulfilment = SalesOrderLineFulfilment(
            organisation_id=order.organisation_id,
            sales_order_id=order.id,
            sales_order_line_id=line.id,
            unit_of_measure_id=line.unit_of_measure_id,
            fg_available_quantity=available,
            fg_covered_quantity=covered,
            production_quantity=shortfall,
            result=PRODUCTION_REQUIRED if shortfall > _ZERO else FROM_STOCK,
        )
        db.add(fulfilment)
        results.append(fulfilment)
        if shortfall > _ZERO:
            requirement = ProductionRequirement(
                organisation_id=order.organisation_id,
                sales_order_id=order.id,
                sales_order_line_id=line.id,
                product_id=product.id,
                quantity=shortfall,
                unit_of_measure_id=product.unit_of_measure_id,
                status=REQUIREMENT_BOM_REQUIRED,
            )
            _snapshot_bom(db, requirement)
            db.add(requirement)
    db.flush()
    return results


def lines_with_fulfilment(db: Session, order: SalesOrder) -> set[int]:
    """Sales Order line ids that already have a fulfilment result."""
    line_ids = [line.id for line in order.lines]
    rows = db.query(SalesOrderLineFulfilment.sales_order_line_id).filter(
        SalesOrderLineFulfilment.sales_order_line_id.in_(line_ids)
    )
    return {row[0] for row in rows}


# --- Lifecycle (Production P1) -------------------------------------------------


@dataclass(frozen=True)
class RequirementChange:
    """One requirement transition, for the caller's audit trail."""

    requirement: ProductionRequirement
    kind: str  # created | quantity_changed | reopened | satisfied | cancelled
    details: str


def _plain(value: Decimal) -> str:
    return format(value.normalize(), "f")


def snapshot_bom(db: Session, requirement: ProductionRequirement) -> None:
    """Resolves a `bom_required` requirement once the product has an active
    BOM: takes the same one-time snapshot hand-off takes and makes it
    `open`. The quantity and unit are untouched; later BOM edits never
    reach the snapshot. The row is locked so two requests cannot both
    snapshot."""
    locked = (
        db.query(ProductionRequirement)
        .filter(ProductionRequirement.id == requirement.id)
        .with_for_update()
        .one()
    )
    if locked.status != REQUIREMENT_BOM_REQUIRED:
        raise ConflictError(f"Only a requirement waiting for a BOM can take one (this one is {locked.status}).")
    _snapshot_bom(db, locked)
    if locked.status != REQUIREMENT_OPEN:
        raise ConflictError("This product still has no active BOM. Activate its BOM first.")
    db.flush()


def cancel_for_order(db: Session, order: SalesOrder, reason: str) -> list[RequirementChange]:
    """The cancelled order's active requirements become `cancelled`, kept
    with their snapshot and history -- including ones satisfied by an
    allocation, which the cancellation releases (only a handed-off order,
    with nothing delivered, can be cancelled). No
    Production Order exists yet, so none has started production; nothing
    moves in inventory."""
    changes = []
    now = datetime.utcnow()
    requirements = (
        db.query(ProductionRequirement)
        .filter(
            ProductionRequirement.sales_order_id == order.id,
            ProductionRequirement.status.in_(REQUIREMENT_ACTIVE + (REQUIREMENT_SATISFIED,)),
        )
        .order_by(ProductionRequirement.id)
        .with_for_update()
        .all()
    )
    for requirement in requirements:
        previous = requirement.status
        requirement.status = REQUIREMENT_CANCELLED
        requirement.cancelled_at = now
        requirement.cancellation_reason = f"Sales Order cancelled: {reason}"
        db.add(requirement)
        changes.append(RequirementChange(requirement, "cancelled", f"{previous} -> cancelled; sales order cancelled: {reason}"))
    db.flush()
    return changes


def recalculate_line(db: Session, order: SalesOrder, line: SalesOrderLine, delivered: Decimal) -> RequirementChange | None:
    """Keeps one order line's requirement consistent with its current
    position -- called in the same transaction as every change that moves
    it (allocation, release, delivery, a confirmed quantity change):

        uncovered demand = ordered - delivered - allocated

    - positive and no requirement yet -> one is created (snapshotting the
      product's active BOM, or `bom_required`); never a second one;
    - positive and active -> its quantity becomes the uncovered demand;
    - positive and `satisfied` -> it becomes active again (e.g. an
      allocation was released on a still-open order);
    - zero or less and active -> `satisfied`;
    - `cancelled` (the order was cancelled) is final and never touched.
    The hand-off assessment record is never rewritten; the BOM snapshot
    and unit never change; nothing moves in Inventory."""
    if order.status == CANCELLED:
        return None  # its demand is withdrawn: nothing is recreated
    requirement = (
        db.query(ProductionRequirement).filter(ProductionRequirement.sales_order_line_id == line.id).with_for_update().first()
    )
    if requirement is not None and requirement.status == REQUIREMENT_CANCELLED:
        return None
    uncovered = line.quantity - delivered - fg_allocation_service.line_allocation(db, line.id)
    label = f"line {line.line_number}"
    if uncovered <= _ZERO:
        if requirement is None or requirement.status not in REQUIREMENT_ACTIVE:
            return None
        previous = requirement.status
        requirement.status = REQUIREMENT_SATISFIED
        requirement.satisfied_at = datetime.utcnow()
        db.flush()
        return RequirementChange(requirement, "satisfied", f"{label}: {previous} -> satisfied; no uncovered demand")
    if requirement is None:
        requirement = ProductionRequirement(
            organisation_id=order.organisation_id,
            sales_order_id=order.id,
            sales_order_line_id=line.id,
            product_id=line.product_id,
            quantity=uncovered,
            unit_of_measure_id=line.unit_of_measure_id,
            status=REQUIREMENT_BOM_REQUIRED,
        )
        _snapshot_bom(db, requirement)
        db.add(requirement)
        db.flush()
        return RequirementChange(requirement, "created", f"{label}: quantity {_plain(uncovered)} ({requirement.status})")
    if requirement.status == REQUIREMENT_SATISFIED:
        requirement.status = REQUIREMENT_OPEN if requirement.bom_id is not None else REQUIREMENT_BOM_REQUIRED
        requirement.satisfied_at = None
        before = requirement.quantity
        requirement.quantity = uncovered
        db.flush()
        return RequirementChange(
            requirement, "reopened", f"{label}: satisfied -> {requirement.status}; quantity {_plain(before)} -> {_plain(uncovered)}"
        )
    if requirement.quantity == uncovered:
        return None
    before = requirement.quantity
    requirement.quantity = uncovered
    db.flush()
    return RequirementChange(requirement, "quantity_changed", f"{label}: quantity {_plain(before)} -> {_plain(uncovered)}")


def recalculate_order(db: Session, order: SalesOrder, delivered: dict[int, Decimal]) -> list[RequirementChange]:
    """recalculate_line for every line of the order."""
    changes = []
    for line in order.lines:
        change = recalculate_line(db, order, line, delivered.get(line.id, _ZERO))
        if change is not None:
            changes.append(change)
    return changes
