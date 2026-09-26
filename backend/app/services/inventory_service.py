"""The one place any module writes a stock-affecting event
(docs/modules/purchase_orders.md #9) -- never insert a StockMovement row
or touch RawMaterialInventory.quantity_on_hand anywhere else. Purchase's
post_receipt/reverse_receipt (docs/modules/purchase_orders.md #38,
Revision 4) are the callers for RECEIPT/RECEIPT_REVERSAL; app/api/inventory.py's
create_adjustment/create_opening_stock are the callers for ADJUSTMENT
(Controlled Stock Adjustments -- a verified physical/system stock
difference, corrected by a new movement, never a direct edit of the
snapshot or an existing movement) and OPENING_STOCK (Controlled Opening
Stock -- the one-time, IN-only movement establishing a pair's starting
balance). A future Production/Sales module issuing stock reuses this
same service rather than maintaining a second, parallel ledger
(docs/ENGINEERING_PRINCIPLES.md #2).

Does not commit -- same convention as audit_service.log_event: the
caller commits this alongside whatever else belongs in the same
transaction (a PurchaseOrderLine.received_quantity update for a receipt;
nothing else for an adjustment or opening stock), so the two succeed or
fail together (task's own "receipt + inventory movement must be atomic"
requirement, extended identically to adjustments and opening stock)."""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleError, ConflictError
from app.core.database import savepoint
from app.models.inventory import (
    ADJUSTMENT,
    ADJUSTMENT_REFERENCE,
    OPENING_STOCK,
    OPENING_STOCK_REFERENCE,
    PRODUCTION_ISSUE,
    RECEIPT,
    RECEIPT_REVERSAL,
    InventoryAdjustment,
    OpeningStockEntry,
    RawMaterialInventory,
    StockMovement,
)


def _insert_movement(db: Session, movement: StockMovement) -> None:
    """The one place a StockMovement row is inserted -- a duplicate (the
    same reference_type/reference_id/movement_type posted twice,
    uq_stock_movements_reference_type_reference_id_movement_type) is
    rejected with a clear error instead of the raw IntegrityError (gap-fix:
    Inventory ledger hardening -- duplicate protection, inventory-level,
    never relying on the caller alone). A legitimate reversal is a
    different movement_type against the same reference, so it is never
    caught by this guard. Not wrapped in its own savepoint: nothing here
    or in any caller (receive_stock/reverse_stock and their own callers)
    touches `db` again after catching IntegrityError -- the exception
    propagates to the API layer's error handler (app/core/error_handlers.py,
    which never touches `db`) and the request-scoped session is then
    discarded via get_db()'s own close(), which rolls back whatever's
    pending. A savepoint here would only be needed if something had to
    keep using this same session afterward."""
    try:
        db.add(movement)
        db.flush()
    except IntegrityError as exc:
        raise ConflictError(
            "This source has already posted this kind of stock movement -- refresh and try again."
        ) from exc


def receive_stock(
    db: Session,
    *,
    organisation_id: int,
    raw_material_id: int,
    warehouse_id: int,
    quantity,
    unit_of_measure_id: int,
    reference_type: str,
    reference_id: int,
    created_by_user_id: int | None,
) -> StockMovement:
    """Inserts the immutable ledger row and applies its effect to the
    current-quantity snapshot in one call. `quantity` must already be
    validated strictly positive by the caller (PurchaseOrderLine's own
    schema-level gt=0, docs/modules/purchase_orders.md #10) -- this
    service doesn't re-validate business rules, only records the
    movement and keeps the snapshot consistent with it. `unit_of_measure_id`
    is the raw material's own stock unit, already resolved by the caller
    -- never re-derived here (gap-fix: Inventory ledger hardening --
    movement UOM)."""
    movement = StockMovement(
        organisation_id=organisation_id,
        raw_material_id=raw_material_id,
        warehouse_id=warehouse_id,
        movement_type=RECEIPT,
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
        raw_material_id=raw_material_id,
        warehouse_id=warehouse_id,
        quantity=quantity,
    )
    return movement


def reverse_stock(
    db: Session,
    *,
    organisation_id: int,
    quantity,
    reference_type: str,
    reference_id: int,
    created_by_user_id: int | None,
) -> StockMovement:
    """Reversing a posted Goods Receipt (docs/modules/purchase_orders.md
    #38, Revision 4) -- a second, negative-quantity ledger row, never an
    edit of the original `RECEIPT` movement it offsets. The correction
    model is always incorrect movement -> reversal -> correct new
    movement; a movement is never edited in place.

    `raw_material_id`, `warehouse_id` and `unit_of_measure_id` are not
    caller-supplied -- they are looked up from the original `RECEIPT`
    movement this reversal targets (the same `reference_type`/
    `reference_id`) and copied from it, so a reversal can never land
    against a different material/warehouse/unit than what it's actually
    offsetting (gap-fix: Inventory ledger hardening -- reversal
    integrity). `quantity` must already be validated strictly positive by
    the caller (the magnitude being reversed); this function negates it
    itself and rejects a magnitude larger than the original movement's
    own quantity -- a reversal can never exceed what it's reversing.
    There is no arbitrary/manual reversal without a valid source: a
    reference with no matching original `RECEIPT` movement is rejected.
    A receipt can only be reversed once -- enforced by the same
    reference_type/reference_id/movement_type uniqueness `_insert_movement`
    already relies on for duplicate protection, since a second reversal
    attempt reuses the same reference. Reuses the exact same
    `_increment_inventory` conditional-UPDATE mechanism `receive_stock`
    does -- adding a negative quantity is a decrement with no separate
    code path."""
    original = (
        db.query(StockMovement)
        .filter(
            StockMovement.organisation_id == organisation_id,
            StockMovement.reference_type == reference_type,
            StockMovement.reference_id == reference_id,
            StockMovement.movement_type == RECEIPT,
        )
        .first()
    )
    if original is None:
        raise BusinessRuleError(
            "There is no posted receipt movement for this source to reverse."
        )
    if quantity > original.quantity:
        raise BusinessRuleError(
            f"Cannot reverse {quantity}, which exceeds the original movement's own quantity ({original.quantity})."
        )

    movement = StockMovement(
        organisation_id=organisation_id,
        raw_material_id=original.raw_material_id,
        warehouse_id=original.warehouse_id,
        movement_type=RECEIPT_REVERSAL,
        quantity=-quantity,
        unit_of_measure_id=original.unit_of_measure_id,
        reference_type=reference_type,
        reference_id=reference_id,
        created_by_user_id=created_by_user_id,
    )
    _insert_movement(db, movement)

    _increment_inventory(
        db,
        organisation_id=organisation_id,
        raw_material_id=original.raw_material_id,
        warehouse_id=original.warehouse_id,
        quantity=-quantity,
    )
    return movement


def adjust_stock(
    db: Session,
    *,
    organisation_id: int,
    raw_material_id: int,
    warehouse_id: int,
    quantity,
    unit_of_measure_id: int,
    reason: str,
    created_by_user_id: int | None,
) -> StockMovement:
    """Controlled Stock Adjustment (docs/modules/purchase_orders.md's own
    "reversal, never edit" correction model, extended here to a verified
    physical/system stock difference that has no prior movement to
    reverse) -- the one explicit, manual way to correct
    quantity_on_hand: a new ADJUSTMENT ledger row, atomically applied to
    the snapshot through the exact same `_increment_inventory`
    conditional-UPDATE every other movement type already uses, never a
    direct write to quantity_on_hand and never an edit of any existing
    StockMovement. `quantity`'s own sign is the adjustment's direction --
    positive is stock in, negative is stock out -- movement_type alone
    (ADJUSTMENT) already distinguishes this from a RECEIPT/RECEIPT_REVERSAL,
    so there is no separate direction column, the same reasoning
    RECEIPT_REVERSAL's own negative quantity already established.
    `unit_of_measure_id` is the raw material's own current stock unit,
    resolved and validated by the caller -- never accepted as arbitrary
    input (gap-fix: Controlled Stock Adjustments -- UOM). `reason` must
    already be validated non-blank by the caller (the API schema's own
    field validator, the same layer ReverseReceiptRequest's own reason
    already is) -- this service doesn't re-validate business rules, only
    records the movement and keeps the snapshot consistent with it."""
    adjustment = InventoryAdjustment(organisation_id=organisation_id, reason=reason)
    db.add(adjustment)
    db.flush()

    movement = StockMovement(
        organisation_id=organisation_id,
        raw_material_id=raw_material_id,
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
        raw_material_id=raw_material_id,
        warehouse_id=warehouse_id,
        quantity=quantity,
    )
    return movement


def issue_for_production(
    db: Session,
    *,
    organisation_id: int,
    raw_material_id: int,
    warehouse_id: int,
    quantity,
    unit_of_measure_id: int,
    reference_type: str,
    reference_id: int,
    created_by_user_id: int | None,
) -> StockMovement:
    """Raw material consumed by recorded production (Production Execution,
    P6) -- a PRODUCTION_ISSUE ledger row with the negative of `quantity`
    (the positive magnitude consumed), applied to the snapshot through the
    same conditional UPDATE every movement uses, so it can never take stock
    below zero (BusinessRuleError, nothing applied). `unit_of_measure_id`
    is the material's own stock unit, resolved by the caller. The
    reference must be unique per consumed material (the ledger's
    reference/movement-type uniqueness is the duplicate guard)."""
    movement = StockMovement(
        organisation_id=organisation_id,
        raw_material_id=raw_material_id,
        warehouse_id=warehouse_id,
        movement_type=PRODUCTION_ISSUE,
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
        raw_material_id=raw_material_id,
        warehouse_id=warehouse_id,
        quantity=-quantity,
    )
    return movement


def _has_any_movement(db: Session, *, raw_material_id: int, warehouse_id: int) -> bool:
    """Whether this (raw_material_id, warehouse_id) pair has any
    StockMovement at all, of any type -- the "must be the first
    movement" check record_opening_stock uses. A plain SELECT, not a DB
    constraint: it can only see what's already committed, so it alone
    can't close a race between two concurrent opening-stock submissions
    for a pair with nothing recorded yet -- that's what OpeningStockEntry's
    own UNIQUE(raw_material_id, warehouse_id) is for (gap-fix: Controlled
    Opening Stock -- must be the first movement)."""
    return (
        db.query(StockMovement.id)
        .filter(StockMovement.raw_material_id == raw_material_id, StockMovement.warehouse_id == warehouse_id)
        .first()
        is not None
    )


def record_opening_stock(
    db: Session,
    *,
    organisation_id: int,
    raw_material_id: int,
    warehouse_id: int,
    quantity,
    unit_of_measure_id: int,
    reason: str,
    created_by_user_id: int | None,
) -> StockMovement:
    """Controlled Opening Stock -- the one-time, IN-only movement that
    establishes the verified physical stock a (raw material, warehouse)
    pair starts with when it's first brought under this ledger's
    control. `quantity` must already be validated strictly positive by
    the caller (the API schema's own field validator) -- opening stock
    is never used to reduce a balance; that's what adjust_stock is for.
    Same atomic shape as receive_stock/adjust_stock: a new append-only
    OPENING_STOCK ledger row, applied to the snapshot through the exact
    same `_increment_inventory` conditional-UPDATE, never a direct write
    to quantity_on_hand and never an edit of any existing StockMovement.

    Duplicate protection (rule 7) is the OpeningStockEntry insert's own
    UNIQUE(raw_material_id, warehouse_id) -- a second opening-stock
    submission for the same pair fails here, before any StockMovement or
    balance change is even attempted, so a rejected duplicate has zero
    effect, not just a rejected *second* effect. Not wrapped in its own
    savepoint, same reasoning `_insert_movement` already documents:
    nothing here or in any caller touches `db` again after catching
    IntegrityError, so there's nothing a savepoint would need to protect
    from being poisoned. `unit_of_measure_id` is the raw material's own
    current stock unit, resolved and validated by the caller -- never
    accepted as arbitrary input, and never a historical re-derivation
    (gap-fix: Controlled Opening Stock -- UOM).

    Opening stock is also rejected outright if this pair already has ANY
    StockMovement on record, of any type -- not just a prior opening
    stock. Opening stock's whole purpose (per its own rules) is
    establishing the starting balance "when it's first brought under
    this ledger's control"; a pair that's already received real receipts
    or adjustments is no longer at that starting point, and letting
    opening stock inject an extra, undated-relative-to-those-events
    balance on top would misrepresent the ledger's own history (gap-fix:
    Controlled Opening Stock -- must be the first movement)."""
    if _has_any_movement(db, raw_material_id=raw_material_id, warehouse_id=warehouse_id):
        raise BusinessRuleError(
            "Opening stock can only be recorded before any other movement exists for this raw material in this warehouse."
        )

    entry = OpeningStockEntry(
        organisation_id=organisation_id, raw_material_id=raw_material_id, warehouse_id=warehouse_id, reason=reason
    )
    try:
        db.add(entry)
        db.flush()
    except IntegrityError as exc:
        raise ConflictError(
            "Opening stock has already been recorded for this raw material in this warehouse."
        ) from exc

    movement = StockMovement(
        organisation_id=organisation_id,
        raw_material_id=raw_material_id,
        warehouse_id=warehouse_id,
        movement_type=OPENING_STOCK,
        quantity=quantity,
        unit_of_measure_id=unit_of_measure_id,
        reference_type=OPENING_STOCK_REFERENCE,
        reference_id=entry.id,
        created_by_user_id=created_by_user_id,
    )
    _insert_movement(db, movement)

    _increment_inventory(
        db,
        organisation_id=organisation_id,
        raw_material_id=raw_material_id,
        warehouse_id=warehouse_id,
        quantity=quantity,
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


@dataclass(frozen=True)
class BalanceReconciliation:
    """One (raw material, warehouse) pair's own comparison between
    RawMaterialInventory.quantity_on_hand (the materialized snapshot)
    and SUM(StockMovement.quantity) for that same pair (what the ledger
    itself implies). Nothing here writes anything -- a mismatch is a
    data-integrity fact to surface, per the same "no silent correction"
    principle already established for adjustments and opening stock; if
    the snapshot is what's wrong, a Controlled Stock Adjustment is the
    fix, never an automatic rewrite from this report (gap-fix: Stock
    Balance -- ledger/balance reconciliation, the gap the Stock Balance
    audit itself noted: nothing previously checked this outside tests)."""

    raw_material_id: int
    warehouse_id: int
    ledger_sum: Decimal
    quantity_on_hand: Decimal

    @property
    def matches(self) -> bool:
        return self.ledger_sum == self.quantity_on_hand

    @property
    def difference(self) -> Decimal:
        """quantity_on_hand - ledger_sum -- positive means the snapshot
        shows more than the ledger accounts for."""
        return self.quantity_on_hand - self.ledger_sum


def get_organisation_quantity_on_hand(db: Session, *, organisation_id: int, raw_material_id: int) -> Decimal:
    """Read-only: the raw material's on-hand quantity across every
    warehouse of the organisation, summed from the same snapshot
    get_quantity_on_hand reads. In the material's own stock unit."""
    total = (
        db.query(func.coalesce(func.sum(RawMaterialInventory.quantity_on_hand), 0))
        .filter(
            RawMaterialInventory.organisation_id == organisation_id,
            RawMaterialInventory.raw_material_id == raw_material_id,
        )
        .scalar()
    )
    return Decimal(str(total))


def get_ledger_sum(db: Session, *, raw_material_id: int, warehouse_id: int) -> Decimal:
    """The balance as the ledger itself implies it -- SUM(quantity) over
    every StockMovement for this pair. Only ever used for reconciliation
    (comparing it against the snapshot) -- never as a live substitute for
    RawMaterialInventory.quantity_on_hand; get_quantity_on_hand above is
    still the one place normal callers read the current balance from."""
    total = (
        db.query(func.sum(StockMovement.quantity))
        .filter(StockMovement.raw_material_id == raw_material_id, StockMovement.warehouse_id == warehouse_id)
        .scalar()
    )
    return total if total is not None else Decimal("0")


def reconcile_balances(db: Session, *, organisation_id: int) -> list[BalanceReconciliation]:
    """Every (raw material, warehouse) pair this organisation has a
    snapshot row for, each compared against what its own ledger sums to.
    Read-only report, not a fix: it never touches quantity_on_hand or
    StockMovement, and never runs automatically -- a caller (the
    reconciliation API endpoint) decides when to ask for it."""
    pairs = (
        db.query(RawMaterialInventory.raw_material_id, RawMaterialInventory.warehouse_id, RawMaterialInventory.quantity_on_hand)
        .filter(RawMaterialInventory.organisation_id == organisation_id)
        .all()
    )
    return [
        BalanceReconciliation(
            raw_material_id=raw_material_id,
            warehouse_id=warehouse_id,
            ledger_sum=get_ledger_sum(db, raw_material_id=raw_material_id, warehouse_id=warehouse_id),
            quantity_on_hand=quantity_on_hand,
        )
        for raw_material_id, warehouse_id, quantity_on_hand in pairs
    ]


def _apply_conditional_update(db: Session, *, raw_material_id: int, warehouse_id: int, quantity) -> bool:
    """One atomic UPDATE that both applies the increment and requires a
    matching row whose resulting balance would stay >= 0 -- never a
    read-then-write, and never a separate clamp-to-zero step (gap-fix:
    Inventory ledger hardening -- negative stock protection, enforced in
    the same statement that would otherwise apply the decrement). Returns
    whether a row matched (i.e. was applied)."""
    rowcount = (
        db.query(RawMaterialInventory)
        .filter(
            RawMaterialInventory.raw_material_id == raw_material_id,
            RawMaterialInventory.warehouse_id == warehouse_id,
            RawMaterialInventory.quantity_on_hand + quantity >= 0,
        )
        .update({"quantity_on_hand": RawMaterialInventory.quantity_on_hand + quantity}, synchronize_session=False)
    )
    return bool(rowcount)


def _reject_negative(db: Session, *, raw_material_id: int, warehouse_id: int, quantity) -> None:
    """Only reachable once `_apply_conditional_update` found no row to
    update -- distinguishes "no snapshot row yet" (fine, the caller
    inserts one) from "a row exists but applying this would go negative"
    (never fine): raises clearly, atomically, with no partial effect --
    the ledger row this call's caller already inserted is still only
    flushed, not committed, so it unwinds with the rest of the
    transaction (gap-fix: Inventory ledger hardening -- negative stock
    protection)."""
    existing = (
        db.query(RawMaterialInventory.quantity_on_hand)
        .filter(RawMaterialInventory.raw_material_id == raw_material_id, RawMaterialInventory.warehouse_id == warehouse_id)
        .scalar()
    )
    on_hand = existing if existing is not None else 0
    raise BusinessRuleError(
        f"This would leave negative stock on hand ({on_hand} on hand, {quantity} requested)."
    )


def _increment_inventory(db: Session, *, organisation_id: int, raw_material_id: int, warehouse_id: int, quantity) -> None:
    """The same atomic-conditional-UPDATE shape
    app/services/job_service.py's claim_pending_jobs already established
    in this codebase, in place of row-locking (docs/audit/PROCUREMENT_AUDIT.md
    #10) -- an UPDATE that both applies the increment and requires a
    matching row in one statement, never a read-then-write. Falls back to
    an INSERT only on this (raw_material_id, warehouse_id) pair's very
    first movement, isolated in a savepoint so a concurrent-insert race
    can't discard the StockMovement row this same call already flushed."""
    if _apply_conditional_update(db, raw_material_id=raw_material_id, warehouse_id=warehouse_id, quantity=quantity):
        return

    existing = (
        db.query(RawMaterialInventory.id)
        .filter(RawMaterialInventory.raw_material_id == raw_material_id, RawMaterialInventory.warehouse_id == warehouse_id)
        .first()
    )
    if existing is not None:
        # A row exists now -- either it already did when the update
        # above ran (blocked there by the negative-stock guard) or a
        # concurrent transaction's own first-ever movement for this same
        # pair won the race and inserted it in the meantime (concurrency:
        # this session's own conditional update above and this existence
        # check are two separate statements, not one atomic step, so
        # another session's commit can land between them). Either way,
        # retry the same guarded update now that a row is known to
        # exist -- only report negative stock if this retry still fails,
        # never on the mere possibility that the earlier miss was really
        # a race (gap-fix: Stock Balance hardening -- concurrency, a
        # transaction that only lost the race to create the row must
        # still have its own quantity correctly applied, not be wrongly
        # rejected).
        if not _apply_conditional_update(db, raw_material_id=raw_material_id, warehouse_id=warehouse_id, quantity=quantity):
            _reject_negative(db, raw_material_id=raw_material_id, warehouse_id=warehouse_id, quantity=quantity)
        return
    if quantity < 0:
        # Nothing on hand yet, and this would still go negative.
        _reject_negative(db, raw_material_id=raw_material_id, warehouse_id=warehouse_id, quantity=quantity)

    try:
        with savepoint(db):
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
        # Lost the race -- another concurrent first movement already
        # inserted the row; fall back to the same negative-guarded
        # conditional UPDATE, now guaranteed to find it.
        if not _apply_conditional_update(db, raw_material_id=raw_material_id, warehouse_id=warehouse_id, quantity=quantity):
            _reject_negative(db, raw_material_id=raw_material_id, warehouse_id=warehouse_id, quantity=quantity)
