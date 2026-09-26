"""Turns a handed-off Sales Order into its fulfilment result and
production demand (Sales S15.2, per the S15.1 decisions).

For each line, in line order and independently of the others:
- Finished Goods first: the product's on-hand quantity across every
  warehouse, as Inventory reports it (finished_goods_inventory_service),
  less what earlier lines of this same order already took;
- the covered part is recorded; any remainder becomes one Production
  Requirement for that line, in the product's own unit;
- the requirement snapshots the product's active BOM (base quantity and
  components, each in its raw material's own unit at that moment); with
  no active BOM it is recorded as `bom_required`, without a snapshot.

A line whose unit is not the product's stock unit is refused: FG stock
and the BOM base are both in that unit, and nothing is converted here.

Records only. Nothing is reserved, allocated, moved or issued; nothing
is scheduled, planned or produced; the Sales Order is never changed.

Lifecycle (Production P1) -- a requirement stays a demand/reference
record, never a production command:
- snapshot_bom: `bom_required` -> `open` once the product has an active
  BOM; the quantity is untouched and the snapshot is never refreshed;
- cancel_for_order: the order's active requirements -> `cancelled` when
  the Sales Order is cancelled (nothing has started production -- no
  Production Orders exist yet);
- resolve_quantity_change: an Admin-confirmed quantity change on an
  assessed line recomputes the shortfall against the stock covered at
  hand-off (the assessment record itself is never rewritten);
- mark_satisfied: `fulfilled` once the order line is delivered in full.
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
    REQUIREMENT_FULFILLED,
    REQUIREMENT_OPEN,
    ProductionRequirement,
    ProductionRequirementComponent,
    SalesOrderLineFulfilment,
)
from app.models.raw_material import RawMaterial
from app.models.sales_order import HANDED_OFF, SalesOrder, SalesOrderLine
from app.services import finished_goods_inventory_service

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

    remaining: dict[int, Decimal] = {}
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
        if product.id not in remaining:
            on_hand = finished_goods_inventory_service.get_organisation_quantity_on_hand(
                db, organisation_id=order.organisation_id, product_id=product.id
            )
            remaining[product.id] = max(Decimal(on_hand or 0), _ZERO)
        available = remaining[product.id]
        covered = min(available, line.quantity)
        shortfall = line.quantity - covered
        remaining[product.id] = available - covered

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
    kind: str  # created | quantity_changed | reopened | cancelled | fulfilled
    details: str


def _plain(value: Decimal) -> str:
    return format(value.normalize(), "f")


def outstanding_quantity(requirement: ProductionRequirement, delivered: Decimal, ordered: Decimal) -> Decimal:
    """The demand still open: the part of the shortfall the order line has
    not yet received. Derived, never stored; zero once fulfilled or
    cancelled. Production output (a later pass) will reduce it too -- it
    never has to equal what is produced."""
    if requirement.status not in REQUIREMENT_ACTIVE:
        return _ZERO
    return min(requirement.quantity, max(ordered - delivered, _ZERO))


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
    with their snapshot and history. Fulfilled ones stay fulfilled. No
    Production Order exists yet, so none has started production; nothing
    moves in inventory."""
    changes = []
    now = datetime.utcnow()
    requirements = (
        db.query(ProductionRequirement)
        .filter(ProductionRequirement.sales_order_id == order.id, ProductionRequirement.status.in_(REQUIREMENT_ACTIVE))
        .order_by(ProductionRequirement.id)
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


def resolve_quantity_change(db: Session, order: SalesOrder, line: SalesOrderLine, new_quantity: Decimal) -> RequirementChange | None:
    """An Admin-confirmed quantity change on an assessed line. The hand-off
    assessment stays as recorded; the shortfall is recomputed against the
    stock it covered then: max(0, new quantity - covered). Then:
    - a new shortfall on a fully covered line creates its requirement
      (snapshotting the product's active BOM, as at hand-off);
    - an active requirement takes the new shortfall, or is cancelled if
      none is left;
    - a requirement cancelled by an earlier reduction returns (to `open`
      with its original snapshot, or `bom_required`) with the new
      shortfall.
    Never touches the snapshot or unit; creates nothing in Production or
    Inventory. Returns what changed, or None."""
    fulfilment = (
        db.query(SalesOrderLineFulfilment).filter(SalesOrderLineFulfilment.sales_order_line_id == line.id).one()
    )
    shortfall = max(new_quantity - fulfilment.fg_covered_quantity, _ZERO)
    requirement = (
        db.query(ProductionRequirement).filter(ProductionRequirement.sales_order_line_id == line.id).with_for_update().first()
    )
    label = f"line {line.line_number}"
    if requirement is None:
        if shortfall == _ZERO:
            return None
        requirement = ProductionRequirement(
            organisation_id=order.organisation_id,
            sales_order_id=order.id,
            sales_order_line_id=line.id,
            product_id=line.product_id,
            quantity=shortfall,
            unit_of_measure_id=line.unit_of_measure_id,
            status=REQUIREMENT_BOM_REQUIRED,
        )
        _snapshot_bom(db, requirement)
        db.add(requirement)
        db.flush()
        return RequirementChange(requirement, "created", f"{label}: quantity {_plain(shortfall)} ({requirement.status})")
    if requirement.status == REQUIREMENT_FULFILLED:
        raise ConflictError(f"The production requirement of {label} is already fulfilled; its quantity cannot change.")
    if requirement.status == REQUIREMENT_CANCELLED:
        if shortfall == _ZERO:
            return None
        previous_quantity = requirement.quantity
        requirement.status = REQUIREMENT_OPEN if requirement.bom_id is not None else REQUIREMENT_BOM_REQUIRED
        requirement.quantity = shortfall
        requirement.cancelled_at = None
        requirement.cancellation_reason = None
        db.add(requirement)
        db.flush()
        return RequirementChange(
            requirement, "reopened",
            f"{label}: cancelled -> {requirement.status}; quantity {_plain(previous_quantity)} -> {_plain(shortfall)}",
        )
    if shortfall == _ZERO:
        previous = requirement.status
        requirement.status = REQUIREMENT_CANCELLED
        requirement.cancelled_at = datetime.utcnow()
        requirement.cancellation_reason = f"Line quantity changed to {_plain(new_quantity)}; covered from stock at hand-off."
        db.add(requirement)
        db.flush()
        return RequirementChange(requirement, "cancelled", f"{label}: {previous} -> cancelled; no shortfall at quantity {_plain(new_quantity)}")
    if shortfall == requirement.quantity:
        return None
    previous_quantity = requirement.quantity
    requirement.quantity = shortfall
    db.add(requirement)
    db.flush()
    return RequirementChange(requirement, "quantity_changed", f"{label}: quantity {_plain(previous_quantity)} -> {_plain(shortfall)}")


def mark_satisfied(db: Session, order: SalesOrder, delivered: dict[int, Decimal]) -> list[RequirementChange]:
    """Active requirements whose order line has been delivered in full
    (delivered >= ordered) become `fulfilled`: the demand they stood for is
    met, whatever stock served it. `delivered` maps order line id to its
    fulfilled quantity (Delivery works it out)."""
    ordered = {line.id: line.quantity for line in order.lines}
    changes = []
    requirements = (
        db.query(ProductionRequirement)
        .filter(ProductionRequirement.sales_order_id == order.id, ProductionRequirement.status.in_(REQUIREMENT_ACTIVE))
        .all()
    )
    for requirement in requirements:
        line_id = requirement.sales_order_line_id
        if delivered.get(line_id, _ZERO) >= ordered[line_id]:
            previous = requirement.status
            requirement.status = REQUIREMENT_FULFILLED
            requirement.fulfilled_at = datetime.utcnow()
            db.add(requirement)
            changes.append(
                RequirementChange(requirement, "fulfilled", f"{previous} -> fulfilled; order line delivered ({_plain(delivered[line_id])})")
            )
    db.flush()
    return changes
