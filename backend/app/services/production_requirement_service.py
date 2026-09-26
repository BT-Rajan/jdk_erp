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
is scheduled, planned or produced; the Sales Order is never changed."""

from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.errors import ConflictError, ValidationError
from app.models.bom import ACTIVE, Bom, BomComponent
from app.models.product import Product
from app.models.production_requirement import (
    FROM_STOCK,
    PRODUCTION_REQUIRED,
    REQUIREMENT_BOM_REQUIRED,
    REQUIREMENT_OPEN,
    ProductionRequirement,
    ProductionRequirementComponent,
    SalesOrderLineFulfilment,
)
from app.models.raw_material import RawMaterial
from app.models.sales_order import HANDED_OFF, SalesOrder
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
