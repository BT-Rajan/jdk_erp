"""Finished Goods allocation: claims on physical FG already on hand, one per
Sales Order line (Reservation + FG Allocation foundation).

    free FG = physical on hand - open allocations          (per product)

Allocation never writes finished_goods_inventory or a movement --
finished_goods_inventory_service stays the only writer of physical stock,
and Delivery still issues through it. This module only keeps the claims
honest:
- allocate: up to the free FG and up to what the line still needs
  (ordered - delivered - already allocated);
- release: back to free FG, with a reason (the caller audits who/when);
- delivery: a line's own allocation is consumed first, and a delivery may
  never take FG allocated to another order (check_delivery).

Concurrency: every path that can *increase* a claim or *reduce* physical
stock first locks the product's finished_goods_inventory rows
(`lock_product`, SELECT ... FOR UPDATE), so allocations, hand-off and
deliveries of one product run one at a time and always see committed
figures. Callers holding a Sales Order row lock take it before this one.
A final guard re-checks `allocated <= on hand` before returning. The
table's CHECK keeps a claim from going negative.

Does not audit or commit: callers log each returned AllocationChange and
commit with the rest of their transaction."""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, ValidationError
from app.models.fg_allocation import FgAllocation
from app.models.finished_goods_inventory import FinishedGoodsInventory
from app.models.sales_order import HANDED_OFF, PARTIALLY_DELIVERED, SalesOrder, SalesOrderLine

_ZERO = Decimal("0")
# Orders whose lines may hold or gain an allocation.
ALLOCATABLE_STATUSES = (HANDED_OFF, PARTIALLY_DELIVERED)


@dataclass(frozen=True)
class AllocationChange:
    """One change to a line's claim, for the caller's audit trail."""

    sales_order_id: int
    sales_order_line_id: int
    product_id: int
    kind: str  # allocated | released | consumed
    before: Decimal
    after: Decimal
    reason: str | None = None


def _plain(value: Decimal) -> str:
    return format(Decimal(value).normalize(), "f")


def lock_product(db: Session, organisation_id: int, product_id: int) -> Decimal:
    """Locks the product's physical stock rows and returns the on-hand
    total across the organisation's warehouses (JDK has one)."""
    rows = (
        db.query(FinishedGoodsInventory)
        .filter(FinishedGoodsInventory.organisation_id == organisation_id, FinishedGoodsInventory.product_id == product_id)
        .with_for_update()
        .all()
    )
    return sum((Decimal(row.quantity_on_hand) for row in rows), _ZERO)


def allocated_total(db: Session, organisation_id: int, product_id: int) -> Decimal:
    total = (
        db.query(func.coalesce(func.sum(FgAllocation.quantity), 0))
        .filter(FgAllocation.organisation_id == organisation_id, FgAllocation.product_id == product_id)
        .scalar()
    )
    return Decimal(str(total))


def line_allocation(db: Session, sales_order_line_id: int) -> Decimal:
    value = db.query(FgAllocation.quantity).filter(FgAllocation.sales_order_line_id == sales_order_line_id).scalar()
    return Decimal(value) if value is not None else _ZERO


def product_position(db: Session, organisation_id: int, product_id: int) -> tuple[Decimal, Decimal, Decimal]:
    """(physical on hand, allocated, free) -- read-only, not locked."""
    on_hand = Decimal(
        str(
            db.query(func.coalesce(func.sum(FinishedGoodsInventory.quantity_on_hand), 0))
            .filter(FinishedGoodsInventory.organisation_id == organisation_id, FinishedGoodsInventory.product_id == product_id)
            .scalar()
        )
    )
    allocated = allocated_total(db, organisation_id, product_id)
    return on_hand, allocated, on_hand - allocated


def _row(db: Session, order: SalesOrder, line: SalesOrderLine) -> FgAllocation:
    row = db.query(FgAllocation).filter(FgAllocation.sales_order_line_id == line.id).with_for_update().first()
    if row is None:
        row = FgAllocation(
            organisation_id=order.organisation_id,
            sales_order_id=order.id,
            sales_order_line_id=line.id,
            product_id=line.product_id,
            unit_of_measure_id=line.unit_of_measure_id,
            quantity=_ZERO,
        )
        db.add(row)
        db.flush()
    return row


def _guard(db: Session, organisation_id: int, product_id: int, on_hand: Decimal) -> None:
    if allocated_total(db, organisation_id, product_id) > on_hand:
        raise ConflictError("Finished Goods allocations would exceed the stock on hand; nothing was changed.")


def allocate(
    db: Session, order: SalesOrder, line: SalesOrderLine, quantity: Decimal, delivered: Decimal, client_reference: str | None = None
) -> AllocationChange | None:
    """Claims `quantity` of free FG for one order line. Refused above the
    free FG, above what the line still needs (ordered - delivered - already
    allocated), for an order that is not handed off / partially delivered,
    or for a line not in its product's stock unit. A repeat of the last
    applied `client_reference` changes nothing (returns None)."""
    if quantity is None or quantity <= _ZERO:
        raise ValidationError("Allocate a positive quantity.", fields={"quantity": "Must be greater than zero."})
    if order.status not in ALLOCATABLE_STATUSES:
        raise ConflictError(f"Finished Goods can only be allocated to an open Sales Order (this one is {order.status}).")
    on_hand = lock_product(db, order.organisation_id, line.product_id)
    free = on_hand - allocated_total(db, order.organisation_id, line.product_id)
    row = _row(db, order, line)
    if client_reference and row.last_client_reference == client_reference:
        return None
    needed = line.quantity - delivered - row.quantity
    if quantity > needed:
        raise ConflictError(f"Line {line.line_number} needs at most {_plain(max(needed, _ZERO))} more; nothing was allocated.")
    if quantity > free:
        raise ConflictError(f"Only {_plain(max(free, _ZERO))} of this product is free to allocate; nothing was allocated.")
    before = row.quantity
    row.quantity = before + quantity
    row.last_client_reference = client_reference
    db.flush()
    _guard(db, order.organisation_id, line.product_id, on_hand)
    return AllocationChange(order.id, line.id, line.product_id, "allocated", before, row.quantity)


def allocate_free_up_to(db: Session, order: SalesOrder, line: SalesOrderLine, wanted: Decimal) -> tuple[Decimal, Decimal]:
    """Hand-off: claims min(free FG, wanted) for a new order's line.
    Returns (free FG seen, quantity allocated)."""
    on_hand = lock_product(db, order.organisation_id, line.product_id)
    free = max(on_hand - allocated_total(db, order.organisation_id, line.product_id), _ZERO)
    take = min(free, wanted)
    if take > _ZERO:
        row = _row(db, order, line)
        row.quantity = row.quantity + take
        db.flush()
        _guard(db, order.organisation_id, line.product_id, on_hand)
    return free, take


def release(
    db: Session, line: SalesOrderLine, quantity: Decimal | None, reason: str, client_reference: str | None = None
) -> AllocationChange | None:
    """Returns `quantity` (all of it when None) of the line's claim to free
    FG. Physical stock is untouched; nothing else is created. None if the
    line holds nothing."""
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError("Say why the allocation is released.", fields={"reason": "Required."})
    row = db.query(FgAllocation).filter(FgAllocation.sales_order_line_id == line.id).with_for_update().first()
    if row is not None and client_reference and row.last_client_reference == client_reference:
        return None  # a retry of the release already applied
    held = row.quantity if row is not None else _ZERO
    if quantity is not None and quantity <= _ZERO:
        raise ValidationError("Release a positive quantity.", fields={"quantity": "Must be greater than zero."})
    if quantity is not None and quantity > held:
        raise ConflictError(f"Line {line.line_number} holds only {_plain(held)}; nothing was released.")
    if row is None or held == _ZERO:
        return None
    amount = held if quantity is None else quantity
    row.quantity = held - amount
    if client_reference:
        row.last_client_reference = client_reference
    db.flush()
    return AllocationChange(line.sales_order_id, line.id, line.product_id, "released", held, row.quantity, reason)


def release_for_order(db: Session, order: SalesOrder, reason: str) -> list[AllocationChange]:
    """Every remaining claim of the order back to free FG (cancellation)."""
    changes = []
    for line in order.lines:
        change = release(db, line, None, reason)
        if change is not None:
            changes.append(change)
    return changes


def clamp_to_line(db: Session, line: SalesOrderLine, delivered: Decimal, reason: str) -> AllocationChange | None:
    """After an Admin quantity reduction: a claim above what the line still
    needs is released down to it."""
    held = line_allocation(db, line.id)
    needed = max(line.quantity - delivered, _ZERO)
    if held <= needed:
        return None
    return release(db, line, held - needed, reason)


def check_delivery(db: Session, organisation_id: int, line: SalesOrderLine, quantity: Decimal) -> None:
    """Before a delivery issues `quantity` for this order line: it may use
    the line's own claim and free FG, never FG claimed by other orders.
    When the stock simply is not there, the existing negative-stock
    protection of the FG writer answers instead (unchanged behaviour)."""
    on_hand = lock_product(db, organisation_id, line.product_id)
    own = line_allocation(db, line.id)
    others = allocated_total(db, organisation_id, line.product_id) - own
    if quantity <= on_hand and quantity > on_hand - others:
        raise ConflictError(
            f"Only {_plain(max(on_hand - others, _ZERO))} of this product can be delivered for line {line.line_number}: "
            "the rest of the stock is allocated to other Sales Orders."
        )


def consume_for_delivery(db: Session, line: SalesOrderLine, quantity: Decimal) -> AllocationChange | None:
    """After the physical issue: the line's own claim shrinks by what was
    delivered (never below zero)."""
    row = db.query(FgAllocation).filter(FgAllocation.sales_order_line_id == line.id).with_for_update().first()
    if row is None or row.quantity == _ZERO:
        return None
    before = row.quantity
    row.quantity = max(before - quantity, _ZERO)
    db.flush()
    return AllocationChange(line.sales_order_id, line.id, line.product_id, "consumed", before, row.quantity)
