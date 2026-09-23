"""The one place any module writes a stock-affecting event
(docs/modules/purchase_orders.md #9) -- never insert a StockMovement row
or touch RawMaterialInventory.quantity_on_hand anywhere else. Purchase's
post_receipt/reverse_receipt (docs/modules/purchase_orders.md #38,
Revision 4) are the callers; a future Production/Sales module issuing
stock reuses this same service rather than maintaining a second, parallel
ledger (docs/ENGINEERING_PRINCIPLES.md #2).

Does not commit -- same convention as audit_service.log_event: the
caller (app/services/purchase_order_service.post_receipt/reverse_receipt)
commits this alongside the PurchaseOrderLine.received_quantity update it
belongs with, so the two succeed or fail together (task's own "receipt +
inventory movement must be atomic" requirement)."""

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.inventory import RECEIPT, RECEIPT_REVERSAL, RawMaterialInventory, StockMovement


def receive_stock(
    db: Session,
    *,
    organisation_id: int,
    raw_material_id: int,
    warehouse_id: int,
    quantity,
    reference_type: str,
    reference_id: int,
    created_by_user_id: int | None,
) -> StockMovement:
    """Inserts the immutable ledger row and applies its effect to the
    current-quantity snapshot in one call. `quantity` must already be
    validated strictly positive by the caller (PurchaseOrderLine's own
    schema-level gt=0, docs/modules/purchase_orders.md #10) -- this
    service doesn't re-validate business rules, only records the
    movement and keeps the snapshot consistent with it."""
    movement = StockMovement(
        organisation_id=organisation_id,
        raw_material_id=raw_material_id,
        warehouse_id=warehouse_id,
        movement_type=RECEIPT,
        quantity=quantity,
        reference_type=reference_type,
        reference_id=reference_id,
        created_by_user_id=created_by_user_id,
    )
    db.add(movement)
    db.flush()

    _increment_inventory(
        db,
        organisation_id=organisation_id,
        raw_material_id=raw_material_id,
        warehouse_id=warehouse_id,
        quantity=quantity,
    )
    return movement


def reverse_stock(
    db: Session,
    *,
    organisation_id: int,
    raw_material_id: int,
    warehouse_id: int,
    quantity,
    reference_type: str,
    reference_id: int,
    created_by_user_id: int | None,
) -> StockMovement:
    """Reversing a posted Goods Receipt (docs/modules/purchase_orders.md
    #38, Revision 4) -- a second, negative-quantity ledger row, never an
    edit of the original `RECEIPT` movement it offsets. `quantity` must
    already be validated strictly positive by the caller (the magnitude
    being reversed); this function negates it itself. Reuses the exact
    same `_increment_inventory` conditional-UPDATE mechanism `receive_stock`
    does -- adding a negative quantity is a decrement with no separate
    code path."""
    movement = StockMovement(
        organisation_id=organisation_id,
        raw_material_id=raw_material_id,
        warehouse_id=warehouse_id,
        movement_type=RECEIPT_REVERSAL,
        quantity=-quantity,
        reference_type=reference_type,
        reference_id=reference_id,
        created_by_user_id=created_by_user_id,
    )
    db.add(movement)
    db.flush()

    _increment_inventory(
        db,
        organisation_id=organisation_id,
        raw_material_id=raw_material_id,
        warehouse_id=warehouse_id,
        quantity=-quantity,
    )
    return movement


def get_quantity_on_hand(db: Session, *, raw_material_id: int, warehouse_id: int):
    """Read-only convenience for a future consumer (e.g. a "current
    stock" display) -- always reads the snapshot, never sums the ledger
    live (that would defeat the point of keeping a snapshot at all)."""
    row = (
        db.query(RawMaterialInventory)
        .filter(
            RawMaterialInventory.raw_material_id == raw_material_id,
            RawMaterialInventory.warehouse_id == warehouse_id,
        )
        .first()
    )
    return row.quantity_on_hand if row is not None else 0


def _increment_inventory(db: Session, *, organisation_id: int, raw_material_id: int, warehouse_id: int, quantity) -> None:
    """The same atomic-conditional-UPDATE shape
    app/services/job_service.py's claim_pending_jobs already established
    in this codebase, in place of row-locking (docs/audit/PROCUREMENT_AUDIT.md
    #10) -- an UPDATE that both applies the increment and requires a
    matching row in one statement, never a read-then-write. Falls back to
    an INSERT only on this (raw_material_id, warehouse_id) pair's very
    first receipt, isolated in a savepoint so a concurrent-insert race
    can't discard the StockMovement row this same call already flushed."""
    rowcount = (
        db.query(RawMaterialInventory)
        .filter(
            RawMaterialInventory.raw_material_id == raw_material_id,
            RawMaterialInventory.warehouse_id == warehouse_id,
        )
        .update({"quantity_on_hand": RawMaterialInventory.quantity_on_hand + quantity}, synchronize_session=False)
    )
    if rowcount:
        return

    try:
        with db.begin_nested():
            db.add(
                RawMaterialInventory(
                    organisation_id=organisation_id,
                    raw_material_id=raw_material_id,
                    warehouse_id=warehouse_id,
                    quantity_on_hand=quantity,
                )
            )
            db.flush()
    except IntegrityError:
        # Lost the race -- another concurrent first-receipt already
        # inserted the row; fall back to the same conditional UPDATE,
        # now guaranteed to find it.
        db.query(RawMaterialInventory).filter(
            RawMaterialInventory.raw_material_id == raw_material_id,
            RawMaterialInventory.warehouse_id == warehouse_id,
        ).update({"quantity_on_hand": RawMaterialInventory.quantity_on_hand + quantity}, synchronize_session=False)
