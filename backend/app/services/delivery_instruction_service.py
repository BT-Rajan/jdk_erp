"""Delivery Instructions (Delivery D2): shipment tranches of a Sales Order.
A Sales Order may be delivered in several tranches, so there is no
one-per-order limit; each instruction's lines carry that shipment's own
quantity, which may be anything above zero (less than what remains is
normal).

The Delivery Scrap Allowance is cumulative per Sales Order, never per
tranche. The order's first instruction copies the Admin setting's %;
every later instruction of the same order copies that same %, so later
setting changes never alter the order. For each Sales Order line
(order_position):
  fulfilled            = sum of quantities on fulfilled instructions
  remaining            = ordered - fulfilled
  ceiling              = ordered x (1 + % / 100)
  remaining permitted  = ceiling - fulfilled
all derived, never stored, and exact (quantities have 4 decimal places,
the % 2, so no rounding is needed). A tranche above the remaining
permitted quantity is flagged -- stopping it belongs to fulfilment.

record_shipment (Delivery D3) changes a pending line's shipment quantity
and pallets -- see its docstring.

Records only: nothing moves or reserves stock, changes the Sales Order,
fulfils or checks payment. The caller checks the permission, audits and
commits."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_CEILING, Decimal

from sqlalchemy.orm import Session

from app.core.errors import ConflictError, ValidationError
from app.models.delivery_instruction import FULFILLED, NOT_FULFILLED, PENDING, DeliveryInstruction, DeliveryInstructionLine
from app.models.organisation import Organisation
from app.models.product import Product
from app.models.sales_order import CANCELLED, COMPLETED, HANDED_OFF, PARTIALLY_DELIVERED, SalesOrder, SalesOrderLine
from app.models.unit import UnitOfMeasure
from app.services import document_numbering, fg_allocation_service, finished_goods_inventory_service, purchase_order_service, uom_conversion

DELIVERABLE_STATUSES = (HANDED_OFF, PARTIALLY_DELIVERED)
_HUNDRED = Decimal("100")


@dataclass(frozen=True)
class LineInput:
    sales_order_line_id: int
    quantity: Decimal


def order_allowance(db: Session, order: SalesOrder) -> Decimal | None:
    """The % locked on the order's first Delivery Instruction, or None
    while it has none (business decision: locked at the first tranche)."""
    return (
        db.query(DeliveryInstruction.scrap_allowance_percent)
        .filter(DeliveryInstruction.sales_order_id == order.id)
        .order_by(DeliveryInstruction.id)
        .limit(1)
        .scalar()
    )


def ceiling(ordered: Decimal, allowance_percent: Decimal) -> Decimal:
    """ordered x (1 + % / 100), exact."""
    return ordered * (_HUNDRED + allowance_percent) / _HUNDRED


def fulfilled_quantity(db: Session, sales_order_line_id: int, *, locking: bool = False) -> Decimal:
    """Sum of this order line's quantities on fulfilled instructions --
    the one source of delivery progress; nothing else stores it. `locking`
    (inside fulfilment, after the Sales Order row lock) reads the latest
    committed rows rather than the transaction's snapshot."""
    query = (
        db.query(DeliveryInstructionLine.quantity)
        .join(DeliveryInstruction, DeliveryInstruction.id == DeliveryInstructionLine.delivery_instruction_id)
        .filter(DeliveryInstructionLine.sales_order_line_id == sales_order_line_id, DeliveryInstruction.status == FULFILLED)
    )
    if locking:
        query = query.with_for_update(read=True)
    total = Decimal("0")
    for (quantity,) in query:
        total += quantity
    return total


@dataclass(frozen=True)
class LinePosition:
    sales_order_line_id: int
    product_id: int
    unit_of_measure_id: int
    ordered_quantity: Decimal
    fulfilled_quantity: Decimal
    remaining_quantity: Decimal
    ceiling_quantity: Decimal
    remaining_permitted_quantity: Decimal


def line_position(db: Session, line: SalesOrderLine, allowance_percent: Decimal, *, locking: bool = False) -> LinePosition:
    fulfilled = fulfilled_quantity(db, line.id, locking=locking)
    top = ceiling(line.quantity, allowance_percent)
    return LinePosition(
        line.id, line.product_id, line.unit_of_measure_id, line.quantity, fulfilled, line.quantity - fulfilled, top, top - fulfilled
    )


def order_position(db: Session, order: SalesOrder) -> tuple[Decimal, bool, list[LinePosition]]:
    """(allowance %, whether it is locked by an instruction, per-line
    positions). Before the first instruction the current setting is shown,
    not yet locked."""
    locked = order_allowance(db, order)
    allowance = locked if locked is not None else db.get(Organisation, order.organisation_id).delivery_scrap_allowance_percent
    return allowance, locked is not None, [line_position(db, line, allowance) for line in order.lines]


def exceeds_permitted(position: LinePosition, quantity: Decimal) -> bool:
    """Would delivering `quantity` take the line above its cumulative ceiling?"""
    return quantity > position.remaining_permitted_quantity


def create(db: Session, order: SalesOrder, lines: list[LineInput], user_id: int, today: date) -> DeliveryInstruction:
    if order.status not in DELIVERABLE_STATUSES:
        raise ConflictError(f"A Delivery Instruction can't be created for a {order.status.replace('_', ' ')} Sales Order.")
    if not lines:
        raise ValidationError("Add at least one line to deliver.", fields={"lines": "At least one line is required."})
    order_lines = {line.id: line for line in order.lines}
    seen: set[int] = set()
    for entry in lines:
        if entry.sales_order_line_id not in order_lines:
            raise ValidationError("A line does not belong to this Sales Order.", fields={"lines": "Invalid line."})
        if entry.sales_order_line_id in seen:
            raise ValidationError("Each Sales Order line can appear only once.", fields={"lines": "Duplicate line."})
        seen.add(entry.sales_order_line_id)

    locked = order_allowance(db, order)
    allowance = locked if locked is not None else db.get(Organisation, order.organisation_id).delivery_scrap_allowance_percent

    defaults = {
        entry.sales_order_line_id: default_pallets(
            db, order.organisation_id, db.get(UnitOfMeasure, order_lines[entry.sales_order_line_id].unit_of_measure_id), entry.quantity
        )
        for entry in lines
    }

    def build(number: str) -> DeliveryInstruction:
        instruction = DeliveryInstruction(
            organisation_id=order.organisation_id,
            delivery_number=number,
            sales_order_id=order.id,
            customer_id=order.customer_id,
            status=PENDING,
            created_by_user_id=user_id,
            scrap_allowance_percent=allowance,
        )
        instruction.lines = [
            DeliveryInstructionLine(
                sales_order_line_id=entry.sales_order_line_id,
                product_id=order_lines[entry.sales_order_line_id].product_id,
                unit_of_measure_id=order_lines[entry.sales_order_line_id].unit_of_measure_id,
                ordered_quantity=order_lines[entry.sales_order_line_id].quantity,
                quantity=entry.quantity,
                pallet_count_default=defaults[entry.sales_order_line_id],
                pallet_count=defaults[entry.sales_order_line_id],
            )
            for entry in lines
        ]
        return instruction

    return document_numbering.insert_with_yearly_number(
        db,
        build=build,
        number_column=DeliveryInstruction.delivery_number,
        organisation_column=DeliveryInstruction.organisation_id,
        organisation_id=order.organisation_id,
        type_digit=document_numbering.DELIVERY_INSTRUCTION_TYPE_DIGIT,
        today=today,
        label="delivery instruction",
    )


# --- Shipment quantity and pallets (Delivery D3) --------------------------------

# The organisation's tonne: its one active "mass" unit with one of these
# codes (business decision, Delivery D3). None, or more than one, means no
# pallet default -- the warehouse enters the count.
TONNE_CODES = ("MT", "T", "TON", "TONNE")
_UNSET = object()


def tonne_unit(db: Session, organisation_id: int) -> UnitOfMeasure | None:
    units = (
        db.query(UnitOfMeasure)
        .filter(
            UnitOfMeasure.organisation_id == organisation_id,
            UnitOfMeasure.is_active.is_(True),
            UnitOfMeasure.dimension == "mass",
            UnitOfMeasure.code.in_(TONNE_CODES),
        )
        .all()
    )
    return units[0] if len(units) == 1 else None


def default_pallets(db: Session, organisation_id: int, unit: UnitOfMeasure | None, quantity: Decimal) -> int | None:
    """max(1, ceil(quantity in tonnes)) through the existing unit
    conversion -- a practical suggestion only, never a constraint on the
    quantity. None when the unit can't be converted to tonnes."""
    tonne = tonne_unit(db, organisation_id)
    ratio = uom_conversion.resolve_conversion_ratio(unit, tonne) if unit is not None and tonne is not None else None
    if ratio is None:
        return None
    return max(1, int((quantity * ratio).to_integral_value(rounding=ROUND_CEILING)))


def record_shipment(
    db: Session,
    instruction: DeliveryInstruction,
    line: DeliveryInstructionLine,
    *,
    quantity: Decimal | None,
    unit_of_measure_id: int | None,
    pallet_count=_UNSET,
    override_reason: str | None,
    is_admin: bool,
) -> list[str]:
    """Changes a pending line's shipment quantity and/or pallets. Returns
    the changes as "field: old -> new" (empty if nothing changed).

    Quantity: positive, in the line's stock unit (no conversion; the
    product must still use it). A changed quantity above the order line's
    remaining permitted quantity (cumulative allowance) needs an Admin,
    with a reason; a change that leaves the quantity alone keeps any
    earlier override. The Sales Order is never changed.
    Pallets: a whole number >= 1. The default is recalculated from the
    quantity every time; the count used follows it unless the warehouse
    set one, which is kept until cleared by sending null. A product that
    can't be converted to tonnes has no default, so its count must be
    entered."""
    if instruction.status != PENDING:
        raise ConflictError(f"Only a pending delivery can be changed (this one is {instruction.status.replace('_', ' ')}).")
    if unit_of_measure_id is not None and unit_of_measure_id != line.unit_of_measure_id:
        raise ValidationError(
            "The quantity must be in the product's stock unit; nothing is converted.",
            fields={"unit_of_measure_id": "Must be the delivery line's stock unit."},
        )
    product = db.get(Product, line.product_id)
    if product is None or product.unit_of_measure_id != line.unit_of_measure_id:
        raise ConflictError("The product's stock unit has changed since this delivery was created; nothing is converted.")

    new_quantity = quantity if quantity is not None else line.quantity
    reason = (override_reason or "").strip() or None
    position = line_position(db, db.get(SalesOrderLine, line.sales_order_line_id), instruction.scrap_allowance_percent)
    if new_quantity == line.quantity and reason is None:
        # Quantity untouched (e.g. a pallet-only change): nothing to re-approve;
        # fulfilment checks the limit again anyway.
        reason = line.quantity_override_reason
    elif exceeds_permitted(position, new_quantity):
        permitted = format(position.remaining_permitted_quantity.normalize(), "f")
        if not is_admin:
            raise ValidationError(
                f"The quantity is above what may still be delivered on this order line ({permitted}).",
                fields={"quantity": "Above the remaining permitted quantity."},
            )
        if reason is None:
            raise ValidationError(
                "An Admin override above the remaining permitted quantity needs a reason.",
                fields={"override_reason": "Required above the remaining permitted quantity."},
            )
    else:
        reason = None

    new_default = default_pallets(db, instruction.organisation_id, db.get(UnitOfMeasure, line.unit_of_measure_id), new_quantity)
    if pallet_count is _UNSET:
        manual = line.pallet_count_manual
        count = line.pallet_count if manual else new_default
    elif pallet_count is None:
        manual, count = False, new_default
    else:
        if isinstance(pallet_count, bool) or not isinstance(pallet_count, int) or pallet_count < 1:
            raise ValidationError("Pallets must be a whole number of at least 1.", fields={"pallet_count": "At least 1."})
        manual, count = True, pallet_count
    if count is None:
        raise ValidationError(
            "This product can't be converted to tonnes -- enter the pallet count.",
            fields={"pallet_count": "Required for this product."},
        )

    changes = []
    for field, old, new in (
        ("quantity", line.quantity, new_quantity),
        ("pallet_count", line.pallet_count, count),
        ("pallet_count_default", line.pallet_count_default, new_default),
        ("pallet_count_manual", line.pallet_count_manual, manual),
        ("quantity_override_reason", line.quantity_override_reason, reason),
    ):
        if old != new:
            changes.append(f"line {line.sales_order_line_id} {field}: {old} -> {new}")
    line.quantity = new_quantity
    line.pallet_count = count
    line.pallet_count_default = new_default
    line.pallet_count_manual = manual
    line.quantity_override_reason = reason
    db.add(line)
    db.flush()
    return changes


# --- Fulfilment states (Delivery D4) ----------------------------------------------


def _conflict_for(status: str) -> ConflictError:
    if status == FULFILLED:
        return ConflictError("This delivery has already been fulfilled.")
    if status == NOT_FULFILLED:
        return ConflictError("This delivery was not fulfilled -- retry it first.")
    return ConflictError(f"This delivery can't do that while it is {status.replace('_', ' ')}.")


def _transition(db: Session, instruction: DeliveryInstruction, from_status: str, values: dict) -> None:
    """Moves the instruction only if it is still in `from_status`, as one
    conditional UPDATE -- a repeated or concurrent request finds nothing to
    change and gets a conflict, so no transition ever applies twice."""
    changed = (
        db.query(DeliveryInstruction)
        .filter(DeliveryInstruction.id == instruction.id, DeliveryInstruction.status == from_status)
        .update(values, synchronize_session=False)
    )
    if not changed:
        db.refresh(instruction)
        raise _conflict_for(instruction.status)
    db.refresh(instruction)


def check_fulfilment(db: Session, instruction: DeliveryInstruction) -> None:
    """A pending instruction of a live order whose every line is within
    its order line's remaining permitted quantity (cumulative allowance,
    counting only fulfilled instructions) -- or carries the Admin override
    recorded when its quantity was set above it (Delivery D3)."""
    if instruction.status != PENDING:
        raise _conflict_for(instruction.status)
    # Serialise fulfilments of the same Sales Order (row lock until commit),
    # so two instructions fulfilled at once can't both pass the cumulative
    # limit or leave a stale order status. SQLite ignores it (one writer).
    order = db.query(SalesOrder).filter(SalesOrder.id == instruction.sales_order_id).with_for_update().one_or_none()
    if order is None or order.status == CANCELLED:
        raise ConflictError("The Sales Order is cancelled; this delivery can't be fulfilled.")
    for line in instruction.lines:
        position = line_position(
            db, db.get(SalesOrderLine, line.sales_order_line_id), instruction.scrap_allowance_percent, locking=True
        )
        if exceeds_permitted(position, line.quantity) and not line.quantity_override_reason:
            permitted = format(position.remaining_permitted_quantity.normalize(), "f")
            raise ConflictError(
                f"Line {line.sales_order_line_id}: {format(line.quantity.normalize(), 'f')} is above what may still be "
                f"delivered on this order line ({permitted}); an Admin must set the quantity with an override reason."
            )


# The Finished Goods movement's source (Delivery D5): one DELIVERY movement
# per Delivery Instruction line, so the ledger's unique (reference_type,
# reference_id, movement_type) rule makes a second issue for the same line
# impossible. The line identifies its Delivery Instruction and Sales Order.
FG_REFERENCE_TYPE = "delivery_instruction_line"


def fulfil(db: Session, instruction: DeliveryInstruction, user_id: int) -> tuple[list, tuple[str, str] | None, list]:
    """pending -> fulfilled, after check_fulfilment, and each line's shipment
    quantity issued from Finished Goods through the existing single writer
    (finished_goods_inventory_service.issue_finished_goods), in the
    product's stock unit, from the organisation's warehouse. All in the
    caller's one transaction: if anything fails -- a duplicate, too little
    stock (never clamped or split) -- nothing is committed, so a fulfilled
    instruction always has exactly its movements and never more. The status
    moves first, as a conditional update, so a concurrent second request
    stops before issuing anything. Then the Sales Order's delivery status
    moves forward if this fulfilment changed it (Delivery D6).

    FG allocation: each line may use its own order line's allocation and
    free FG, never FG allocated to another Sales Order
    (fg_allocation_service.check_delivery, under the product's stock lock);
    after the physical issue the line's own allocation shrinks by what was
    delivered. Returns the movements, the order's (old, new) status if it
    changed, and the allocation changes."""
    check_fulfilment(db, instruction)
    for line in instruction.lines:
        product = db.get(Product, line.product_id)
        if product is None or product.unit_of_measure_id != line.unit_of_measure_id:
            raise ConflictError("A product's stock unit has changed since this delivery was created; nothing is converted.")
    _transition(db, instruction, PENDING, {"status": FULFILLED, "fulfilled_at": datetime.utcnow(), "fulfilled_by_user_id": user_id})
    warehouse = purchase_order_service.default_warehouse(db, instruction.organisation_id)
    movements, allocation_changes = [], []
    for line in instruction.lines:
        order_line = db.get(SalesOrderLine, line.sales_order_line_id)
        fg_allocation_service.check_delivery(db, instruction.organisation_id, order_line, line.quantity)
        movements.append(
            finished_goods_inventory_service.issue_finished_goods(
                db,
                organisation_id=instruction.organisation_id,
                product_id=line.product_id,
                warehouse_id=warehouse.id,
                quantity=line.quantity,
                unit_of_measure_id=line.unit_of_measure_id,
                reference_type=FG_REFERENCE_TYPE,
                reference_id=line.id,
                created_by_user_id=user_id,
            )
        )
        consumed = fg_allocation_service.consume_for_delivery(db, order_line, line.quantity)
        if consumed is not None:
            allocation_changes.append(consumed)
    status_change = refresh_order_delivery_status(db, db.get(SalesOrder, instruction.sales_order_id))
    return movements, status_change, allocation_changes


def mark_not_fulfilled(db: Session, instruction: DeliveryInstruction, user_id: int, reason: str) -> None:
    """pending -> not_fulfilled with its mandatory reason; counts for nothing."""
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError("Say why the delivery was not fulfilled.", fields={"reason": "Required."})
    _transition(
        db,
        instruction,
        PENDING,
        {"status": NOT_FULFILLED, "not_fulfilled_reason": reason, "not_fulfilled_at": datetime.utcnow(), "not_fulfilled_by_user_id": user_id},
    )


def retry(db: Session, instruction: DeliveryInstruction) -> None:
    """not_fulfilled -> pending: the same instruction is attempted again
    (its quantity may be reviewed first). The failed attempt stays in the
    audit trail."""
    _transition(
        db,
        instruction,
        NOT_FULFILLED,
        {"status": PENDING, "not_fulfilled_reason": None, "not_fulfilled_at": None, "not_fulfilled_by_user_id": None},
    )


# --- Sales Order delivery progress (Delivery D6) ---------------------------------


def order_delivery_status(db: Session, order: SalesOrder) -> str:
    """handed_off (nothing fulfilled), partially_delivered (something, not
    every line), completed (every line's fulfilled >= its ordered quantity
    -- the allowance is a ceiling, never a target). Per line: one
    product's quantity never counts for another. Only fulfilled
    instructions count."""
    fulfilled = [fulfilled_quantity(db, line.id, locking=True) for line in order.lines]
    if all(done >= line.quantity for done, line in zip(fulfilled, order.lines)):
        return COMPLETED
    if any(done > 0 for done in fulfilled):
        return PARTIALLY_DELIVERED
    return HANDED_OFF


_FORWARD = {HANDED_OFF: (PARTIALLY_DELIVERED, COMPLETED), PARTIALLY_DELIVERED: (COMPLETED,)}


def refresh_order_delivery_status(db: Session, order: SalesOrder) -> tuple[str, str] | None:
    """Called only inside a successful fulfilment (same transaction, order
    row already locked). Moves the order forward -- handed_off ->
    partially_delivered -> completed -- never back, and never touches a
    cancelled or completed order. Returns (old, new) when it changed."""
    old = order.status
    new = order_delivery_status(db, order)
    if new not in _FORWARD.get(old, ()):
        return None
    order.status = new
    db.add(order)
    db.flush()
    return old, new
