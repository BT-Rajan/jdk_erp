"""The one place any module writes a Finished Goods stock-affecting
event -- never insert a FinishedGoodsMovement row or touch
FinishedGoodsInventory.quantity_on_hand anywhere else. A deliberately
separate ledger and service from app/services/inventory_service.py
(Raw Material Inventory): a Product completing production or being
delivered is a different business event, against a different entity,
from a raw material being received or adjusted, and this module's own
founding rule is that the two must never share a table or a writer.

`adjust_finished_goods_stock` is called today by
app/api/finished_goods_inventory.py's create_finished_goods_adjustment
-- the one Finished Goods write action with a real caller in this
codebase right now, the same "verified physical/system stock
difference, corrected by a new movement, never a direct edit" principle
app/services/inventory_service.py's own adjust_stock already
establishes for Raw Materials.

`receive_finished_goods` (PRODUCTION_COMPLETION, IN) and
`issue_finished_goods` (DELIVERY, OUT) have no caller yet: this
codebase has no Production Completion or Delivery/Dispatch workflow to
call them (inspected before writing this module -- ProductionLine is a
production *resource* master with no completion/work-order concept, and
there is no Delivery/Dispatch/Sales Order model or API anywhere). They
exist now as the integration points a future Production module and a
future Delivery module call into, the same "reuse this same service
rather than maintaining a second, parallel ledger" principle
inventory_service.py's own docstring already states for a future
Production/Sales consumer of Raw Material Inventory. Until such a
module exists, nothing in this codebase invokes them outside tests.

Does not commit -- same convention as inventory_service.py and
audit_service.log_event: the caller commits this alongside whatever
else belongs in the same transaction, so the two succeed or fail
together."""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleError, ConflictError
from app.models.finished_goods_inventory import (
    ADJUSTMENT,
    ADJUSTMENT_REFERENCE,
    DELIVERY,
    PRODUCTION_COMPLETION,
    FinishedGoodsAdjustment,
    FinishedGoodsInventory,
    FinishedGoodsMovement,
)


def _insert_movement(db: Session, movement: FinishedGoodsMovement) -> None:
    """The one place a FinishedGoodsMovement row is inserted -- a
    duplicate (the same reference_type/reference_id/movement_type
    posted twice,
    uq_finished_goods_movements_reference_type_reference_id_movement_type)
    is rejected with a clear error instead of the raw IntegrityError,
    mirroring app/services/inventory_service.py's own _insert_movement
    exactly. Not wrapped in its own savepoint, for the identical reason
    that function documents: nothing here or in any caller touches `db`
    again after catching IntegrityError, so the exception propagates to
    the API layer's error handler and the request-scoped session is
    discarded via get_db()'s own close(), which rolls back whatever's
    pending."""
    try:
        db.add(movement)
        db.flush()
    except IntegrityError as exc:
        raise ConflictError(
            "This source has already posted this kind of Finished Goods stock movement -- refresh and try again."
        ) from exc


def receive_finished_goods(
    db: Session,
    *,
    organisation_id: int,
    product_id: int,
    warehouse_id: int,
    quantity,
    unit_of_measure_id: int,
    reference_type: str,
    reference_id: int,
    created_by_user_id: int | None,
) -> FinishedGoodsMovement:
    """Finished Goods production/completion -- always IN. `quantity` must
    already be validated strictly positive by the caller; this service
    doesn't re-validate business rules, only records the movement and
    keeps the snapshot consistent with it. `unit_of_measure_id` is the
    product's own stock unit, already resolved by the caller -- never
    re-derived here, mirroring receive_stock's own movement-UOM
    discipline.

    No caller in this codebase invokes this yet -- see this module's own
    docstring. A future Production Completion event is this function's
    intended caller, supplying its own reference_type/reference_id the
    same way a Goods Receipt line supplies RECEIPT's."""
    movement = FinishedGoodsMovement(
        organisation_id=organisation_id,
        product_id=product_id,
        warehouse_id=warehouse_id,
        movement_type=PRODUCTION_COMPLETION,
        quantity=quantity,
        unit_of_measure_id=unit_of_measure_id,
        reference_type=reference_type,
        reference_id=reference_id,
        created_by_user_id=created_by_user_id,
    )
    _insert_movement(db, movement)

    _increment_inventory(
        db,
        organisation_id=organisation_id,
        product_id=product_id,
        warehouse_id=warehouse_id,
        quantity=quantity,
    )
    return movement


def issue_finished_goods(
    db: Session,
    *,
    organisation_id: int,
    product_id: int,
    warehouse_id: int,
    quantity,
    unit_of_measure_id: int,
    reference_type: str,
    reference_id: int,
    created_by_user_id: int | None,
) -> FinishedGoodsMovement:
    """Finished Goods delivery/dispatch -- always OUT. `quantity` is the
    positive magnitude being delivered, validated strictly positive by
    the caller; this function negates it itself when writing the
    movement (mirroring how reverse_stock takes a positive magnitude and
    negates it for RECEIPT_REVERSAL), so a caller never has to
    pre-negate a quantity by hand. `unit_of_measure_id` is the product's
    own stock unit, already resolved by the caller.

    No caller in this codebase invokes this yet -- see this module's own
    docstring. A future Delivery/Dispatch event is this function's
    intended caller. Subject to the same never-negative guard every
    other movement here goes through -- a delivery for more than is on
    hand is rejected, not clamped."""
    movement = FinishedGoodsMovement(
        organisation_id=organisation_id,
        product_id=product_id,
        warehouse_id=warehouse_id,
        movement_type=DELIVERY,
        quantity=-quantity,
        unit_of_measure_id=unit_of_measure_id,
        reference_type=reference_type,
        reference_id=reference_id,
        created_by_user_id=created_by_user_id,
    )
    _insert_movement(db, movement)

    _increment_inventory(
        db,
        organisation_id=organisation_id,
        product_id=product_id,
        warehouse_id=warehouse_id,
        quantity=-quantity,
    )
    return movement


def adjust_finished_goods_stock(
    db: Session,
    *,
    organisation_id: int,
    product_id: int,
    warehouse_id: int,
    quantity,
    unit_of_measure_id: int,
    reason: str,
    created_by_user_id: int | None,
) -> FinishedGoodsMovement:
    """Controlled Finished Goods Stock Adjustment -- the one explicit,
    manual way to correct quantity_on_hand for a Product: a new
    ADJUSTMENT ledger row, atomically applied to the snapshot, never a
    direct write to quantity_on_hand and never an edit of any existing
    FinishedGoodsMovement. `quantity`'s own sign is the adjustment's
    direction -- positive is stock in, negative is stock out --
    mirroring app/services/inventory_service.py's own adjust_stock
    exactly. `reason` must already be validated non-blank by the caller
    (the API schema's own field validator) -- this service doesn't
    re-validate business rules, only records the movement and keeps the
    snapshot consistent with it. This is the one Finished Goods write
    action wired to a real API endpoint today -- unlike
    receive_finished_goods/issue_finished_goods, it doesn't depend on a
    Production or Delivery module existing first."""
    adjustment = FinishedGoodsAdjustment(organisation_id=organisation_id, reason=reason)
    db.add(adjustment)
    db.flush()

    movement = FinishedGoodsMovement(
        organisation_id=organisation_id,
        product_id=product_id,
        warehouse_id=warehouse_id,
        movement_type=ADJUSTMENT,
        quantity=quantity,
        unit_of_measure_id=unit_of_measure_id,
        reference_type=ADJUSTMENT_REFERENCE,
        reference_id=adjustment.id,
        created_by_user_id=created_by_user_id,
    )
    _insert_movement(db, movement)

    _increment_inventory(
        db,
        organisation_id=organisation_id,
        product_id=product_id,
        warehouse_id=warehouse_id,
        quantity=quantity,
    )
    return movement


def get_quantity_on_hand(db: Session, *, product_id: int, warehouse_id: int):
    """Read-only: always reads the snapshot, never sums the ledger live,
    mirroring inventory_service.get_quantity_on_hand exactly."""
    row = (
        db.query(FinishedGoodsInventory)
        .filter(
            FinishedGoodsInventory.product_id == product_id,
            FinishedGoodsInventory.warehouse_id == warehouse_id,
        )
        .first()
    )
    return row.quantity_on_hand if row is not None else 0


def list_stock_positions(db: Session, *, organisation_id: int) -> list[FinishedGoodsInventory]:
    """Every (Product, Warehouse) pair this organisation has a Finished
    Goods snapshot row for -- the Stock Position screen's own data
    source. Read-only, no pagination: the same "plain list, fetch and
    render" shape the Raw Material reconciliation report already
    established for a per-organisation inventory listing of this size."""
    return (
        db.query(FinishedGoodsInventory)
        .filter(FinishedGoodsInventory.organisation_id == organisation_id)
        .order_by(FinishedGoodsInventory.product_id, FinishedGoodsInventory.warehouse_id)
        .all()
    )


@dataclass(frozen=True)
class MovementHistoryEntry:
    """One FinishedGoodsMovement row, decorated with the running balance
    it produced -- rule 6's own "resulting balance" requirement, which
    the ledger itself doesn't store (a movement only ever records its
    own delta, the same as StockMovement). Computed here, from the
    ledger alone, never read from -- or compared against -- the
    snapshot, so the movement history stays a pure function of its own
    append-only rows."""

    movement: FinishedGoodsMovement
    resulting_balance: Decimal


def get_movement_history(db: Session, *, product_id: int, warehouse_id: int) -> list[MovementHistoryEntry]:
    """Every FinishedGoodsMovement for this (Product, Warehouse) pair,
    newest first, each carrying the balance it left the pair at. The
    running balance is computed by walking the ledger in chronological
    order and accumulating -- a plain Python cumulative sum rather than
    a SQL window function, for the same MySQL/SQLite portability
    reasoning already governing this codebase's other fixed-set/derived-
    value choices."""
    movements = (
        db.query(FinishedGoodsMovement)
        .filter(FinishedGoodsMovement.product_id == product_id, FinishedGoodsMovement.warehouse_id == warehouse_id)
        .order_by(FinishedGoodsMovement.created_at, FinishedGoodsMovement.id)
        .all()
    )
    running = Decimal("0")
    entries: list[MovementHistoryEntry] = []
    for movement in movements:
        running += movement.quantity
        entries.append(MovementHistoryEntry(movement=movement, resulting_balance=running))
    entries.reverse()
    return entries


def get_ledger_sum(db: Session, *, product_id: int, warehouse_id: int) -> Decimal:
    """The balance as the ledger itself implies it -- SUM(quantity) over
    every FinishedGoodsMovement for this pair. Used only for test-level
    reconciliation against the snapshot (rule 9's own "reconciliation" is
    explicitly Raw-Material-only reporting scope; this helper is not
    exposed as its own report here, only used to prove the two agree)."""
    total = (
        db.query(func.sum(FinishedGoodsMovement.quantity))
        .filter(FinishedGoodsMovement.product_id == product_id, FinishedGoodsMovement.warehouse_id == warehouse_id)
        .scalar()
    )
    return total if total is not None else Decimal("0")


def _apply_conditional_update(db: Session, *, product_id: int, warehouse_id: int, quantity) -> bool:
    """One atomic UPDATE that both applies the increment and requires a
    matching row whose resulting balance would stay >= 0 -- never a
    read-then-write, mirroring inventory_service._apply_conditional_update
    exactly, scoped to FinishedGoodsInventory. Returns whether a row
    matched (i.e. was applied)."""
    rowcount = (
        db.query(FinishedGoodsInventory)
        .filter(
            FinishedGoodsInventory.product_id == product_id,
            FinishedGoodsInventory.warehouse_id == warehouse_id,
            FinishedGoodsInventory.quantity_on_hand + quantity >= 0,
        )
        .update({"quantity_on_hand": FinishedGoodsInventory.quantity_on_hand + quantity}, synchronize_session=False)
    )
    return bool(rowcount)


def _reject_negative(db: Session, *, product_id: int, warehouse_id: int, quantity) -> None:
    """Only reachable once `_apply_conditional_update` found no row to
    update -- mirrors inventory_service._reject_negative exactly."""
    existing = (
        db.query(FinishedGoodsInventory.quantity_on_hand)
        .filter(FinishedGoodsInventory.product_id == product_id, FinishedGoodsInventory.warehouse_id == warehouse_id)
        .scalar()
    )
    on_hand = existing if existing is not None else 0
    raise BusinessRuleError(
        f"This would leave negative Finished Goods stock on hand ({on_hand} on hand, {quantity} requested)."
    )


def _increment_inventory(db: Session, *, organisation_id: int, product_id: int, warehouse_id: int, quantity) -> None:
    """The same atomic-conditional-UPDATE-with-insert-fallback shape
    inventory_service._increment_inventory already established for Raw
    Material Inventory, applied to FinishedGoodsInventory. Falls back to
    an INSERT only on this (product_id, warehouse_id) pair's very first
    movement, isolated in a savepoint so a concurrent-insert race can't
    discard the FinishedGoodsMovement row this same call already
    flushed."""
    if _apply_conditional_update(db, product_id=product_id, warehouse_id=warehouse_id, quantity=quantity):
        return

    existing = (
        db.query(FinishedGoodsInventory.id)
        .filter(FinishedGoodsInventory.product_id == product_id, FinishedGoodsInventory.warehouse_id == warehouse_id)
        .first()
    )
    if existing is not None:
        # A row exists now -- either it already did when the update
        # above ran (blocked there by the negative-stock guard) or a
        # concurrent transaction's own first-ever movement for this same
        # pair won the race and inserted it in the meantime. Either way,
        # retry the same guarded update now that a row is known to
        # exist -- only report negative stock if this retry still fails.
        if not _apply_conditional_update(db, product_id=product_id, warehouse_id=warehouse_id, quantity=quantity):
            _reject_negative(db, product_id=product_id, warehouse_id=warehouse_id, quantity=quantity)
        return
    if quantity < 0:
        # Nothing on hand yet, and this would still go negative.
        _reject_negative(db, product_id=product_id, warehouse_id=warehouse_id, quantity=quantity)

    try:
        with db.begin_nested():
            db.add(
                FinishedGoodsInventory(
                    organisation_id=organisation_id,
                    product_id=product_id,
                    warehouse_id=warehouse_id,
                    quantity_on_hand=quantity,
                )
            )
            db.flush()
    except IntegrityError:
        # Lost the race -- another concurrent first movement already
        # inserted the row; fall back to the same negative-guarded
        # conditional UPDATE, now guaranteed to find it.
        if not _apply_conditional_update(db, product_id=product_id, warehouse_id=warehouse_id, quantity=quantity):
            _reject_negative(db, product_id=product_id, warehouse_id=warehouse_id, quantity=quantity)
