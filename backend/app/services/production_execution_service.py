"""Production Execution (P6): what actually happened during production --
the first production step that changes Inventory, only through the
existing single writers:

- raw materials: inventory_service.issue_for_production (PRODUCTION_ISSUE,
  negative, one movement per consumed material, referencing that
  execution's material row);
- finished goods: finished_goods_inventory_service.receive_finished_goods
  (PRODUCTION_COMPLETION, referencing the execution).

record() is one atomic transaction (the caller commits once): the order
row is locked, every material is checked against its locked stock row
first (all shortages reported together), then every movement is posted;
any failure raises before commit, so ledgers, balances, the execution and
the order's status are all left exactly as they were.

Consumption = component quantity x actual quantity / BOM base quantity,
from the order's frozen BOM snapshot, in each raw material's own unit --
never re-resolving the BOM, never converting. The FG receipt is in the
order's production unit. Output is never assigned to a customer, and
Production Requirements and allocations are not touched: demand, supply
and allocation stay separate.

Duplicates: a `client_reference` already posted returns that execution
(nothing is posted again); the ledgers' reference uniqueness is the last
guard. Separate executions of the same order are separate events."""

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleError, ConflictError, NotFoundError, ValidationError
from app.models.inventory import PRODUCTION_EXECUTION_MATERIAL_REFERENCE, RawMaterialInventory
from app.models.product import Product
from app.models.production_execution import (
    EXECUTION_POSTED,
    PRODUCTION_EXECUTION_REFERENCE,
    ProductionExecution,
    ProductionExecutionMaterial,
)
from app.models.production_order import (
    ORDER_COMPLETED,
    ORDER_EXECUTABLE,
    ORDER_IN_PROGRESS,
    ORDER_ISSUED,
    ORDER_PARTIALLY_COMPLETED,
    ProductionOrder,
)
from app.models.raw_material import RawMaterial
from app.services import bom_service, finished_goods_inventory_service, inventory_service, purchase_order_service

_ZERO = Decimal("0")


def _plain(value) -> str:
    return format(Decimal(value).normalize(), "f")


def produced_quantity(db: Session, order_id: int) -> Decimal:
    """Always the sum of the order's posted executions -- never a stored
    figure that could drift from them."""
    total = (
        db.query(func.coalesce(func.sum(ProductionExecution.produced_quantity), 0))
        .filter(ProductionExecution.production_order_id == order_id, ProductionExecution.status == EXECUTION_POSTED)
        .scalar()
    )
    return Decimal(str(total))


def _lock_order(db: Session, organisation_id: int, order_id: int) -> ProductionOrder:
    order = (
        db.query(ProductionOrder)
        .filter(ProductionOrder.id == order_id, ProductionOrder.organisation_id == organisation_id)
        .with_for_update()
        .first()
    )
    if order is None:
        raise NotFoundError("Production order not found.")
    return order


def _refuse_status(order: ProductionOrder) -> None:
    if order.status in ORDER_EXECUTABLE:
        return
    messages = {
        "draft": "A draft Production Order cannot be executed; issue it first.",
        "completed": "This Production Order is already completed.",
        "cancelled": "A cancelled Production Order cannot be executed.",
    }
    raise ConflictError(messages.get(order.status, f"A {order.status} Production Order cannot be executed."))


def start(db: Session, organisation_id: int, order_id: int, user_id: int) -> ProductionOrder:
    """issued -> in_progress: execution has begun (nothing is posted)."""
    order = _lock_order(db, organisation_id, order_id)
    if order.status != ORDER_ISSUED:
        raise ConflictError(f"Only an issued Production Order can be started (this one is {order.status}).")
    order.status = ORDER_IN_PROGRESS
    order.started_at = datetime.utcnow()
    order.started_by_user_id = user_id
    db.flush()
    return order


def record(
    db: Session,
    organisation_id: int,
    order_id: int,
    quantity: Decimal,
    executed_at: datetime | None,
    notes: str | None,
    client_reference: str | None,
    user_id: int,
) -> tuple[ProductionExecution, bool]:
    """Posts one production event. Returns (execution, created); created is
    False when `client_reference` was already posted for this order (a
    retry) -- nothing is posted again."""
    order = _lock_order(db, organisation_id, order_id)
    reference = (client_reference or "").strip() or None
    if reference is not None:
        existing = (
            db.query(ProductionExecution)
            .filter(ProductionExecution.organisation_id == organisation_id, ProductionExecution.client_reference == reference)
            .first()
        )
        if existing is not None:
            if existing.production_order_id != order.id or existing.produced_quantity != quantity:
                raise ConflictError("This execution reference was already used for a different production record.")
            return existing, False

    _refuse_status(order)
    if quantity is None or quantity <= _ZERO:
        raise ValidationError("Enter the positive quantity actually produced.", fields={"produced_quantity": "Must be greater than zero."})
    already = produced_quantity(db, order.id)
    remaining = order.quantity - already
    if quantity > remaining:
        raise ConflictError(
            f"Only {_plain(remaining)} remains on this Production Order (planned {_plain(order.quantity)}, produced "
            f"{_plain(already)}); producing more than the order is not allowed."
        )
    now = datetime.utcnow()
    if executed_at is not None:
        if executed_at.tzinfo is not None:  # stored naive-UTC like every timestamp here
            executed_at = executed_at.astimezone(UTC).replace(tzinfo=None)
        if executed_at > now:
            raise ValidationError("The execution time cannot be in the future.", fields={"executed_at": "In the future."})
    product = db.get(Product, order.product_id)
    if product is None or product.unit_of_measure_id != order.unit_of_measure_id:
        raise ConflictError("The product's production unit no longer matches the order; nothing is converted.")
    if not order.components or not order.bom_base_quantity:
        raise ConflictError("This Production Order has no BOM snapshot; it cannot be executed.")

    # Consumption from the frozen snapshot, in each material's own unit.
    needs: list[tuple[RawMaterial, Decimal, int]] = []
    for component in order.components:
        material = db.get(RawMaterial, component.raw_material_id)
        if material.unit_of_measure_id != component.unit_of_measure_id:
            raise ConflictError(f"{material.name}'s stock unit differs from the order's BOM snapshot; nothing is converted.")
        consumption = bom_service.required_quantity(component.quantity, quantity, order.bom_base_quantity)
        if consumption <= _ZERO:
            raise ConflictError(f"The consumption of {material.name} rounds to zero for this quantity.")
        needs.append((material, consumption, component.unit_of_measure_id))

    warehouse = purchase_order_service.default_warehouse(db, organisation_id)
    # All-or-nothing: check every material under its stock-row lock first.
    shortages = []
    for material, consumption, _ in needs:
        row = (
            db.query(RawMaterialInventory)
            .filter(RawMaterialInventory.raw_material_id == material.id, RawMaterialInventory.warehouse_id == warehouse.id)
            .with_for_update()
            .first()
        )
        on_hand = Decimal(row.quantity_on_hand) if row is not None else _ZERO
        if on_hand < consumption:
            shortages.append(f"{material.name}: needs {_plain(consumption)}, {_plain(on_hand)} on hand")
    if shortages:
        raise BusinessRuleError("Not enough raw material; nothing was posted. " + "; ".join(shortages) + ".")

    sequence = (
        db.query(func.coalesce(func.max(ProductionExecution.sequence), 0)).filter(ProductionExecution.production_order_id == order.id).scalar()
        + 1
    )
    execution = ProductionExecution(
        organisation_id=organisation_id,
        production_order_id=order.id,
        sequence=sequence,
        produced_quantity=quantity,
        unit_of_measure_id=order.unit_of_measure_id,
        executed_at=executed_at or now,
        notes=(notes or "").strip() or None,
        status=EXECUTION_POSTED,
        client_reference=reference,
        recorded_by_user_id=user_id,
    )
    db.add(execution)
    db.flush()
    for material, consumption, unit_id in needs:
        line = ProductionExecutionMaterial(raw_material_id=material.id, quantity=consumption, unit_of_measure_id=unit_id)
        execution.materials.append(line)
        db.flush()
        movement = inventory_service.issue_for_production(
            db,
            organisation_id=organisation_id,
            raw_material_id=material.id,
            warehouse_id=warehouse.id,
            quantity=consumption,
            unit_of_measure_id=unit_id,
            reference_type=PRODUCTION_EXECUTION_MATERIAL_REFERENCE,
            reference_id=line.id,
            created_by_user_id=user_id,
        )
        line.stock_movement_id = movement.id
    fg_movement = finished_goods_inventory_service.receive_finished_goods(
        db,
        organisation_id=organisation_id,
        product_id=order.product_id,
        warehouse_id=warehouse.id,
        quantity=quantity,
        unit_of_measure_id=order.unit_of_measure_id,
        reference_type=PRODUCTION_EXECUTION_REFERENCE,
        reference_id=execution.id,
        created_by_user_id=user_id,
    )
    execution.fg_movement_id = fg_movement.id
    order.status = ORDER_COMPLETED if already + quantity >= order.quantity else ORDER_PARTIALLY_COMPLETED
    if order.started_at is None:
        order.started_at, order.started_by_user_id = now, user_id
    db.flush()
    return execution, True
