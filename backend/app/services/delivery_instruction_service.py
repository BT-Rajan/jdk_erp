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

Records only: nothing moves or reserves stock, changes the Sales Order,
fulfils, counts pallets or checks payment. The caller checks the
permission, audits and commits."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.errors import ConflictError, ValidationError
from app.models.delivery_instruction import FULFILLED, PENDING, DeliveryInstruction, DeliveryInstructionLine
from app.models.organisation import Organisation
from app.models.sales_order import HANDED_OFF, PARTIALLY_DELIVERED, SalesOrder, SalesOrderLine
from app.services import document_numbering

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


def fulfilled_quantity(db: Session, sales_order_line_id: int) -> Decimal:
    total = Decimal("0")
    for (quantity,) in (
        db.query(DeliveryInstructionLine.quantity)
        .join(DeliveryInstruction, DeliveryInstruction.id == DeliveryInstructionLine.delivery_instruction_id)
        .filter(DeliveryInstructionLine.sales_order_line_id == sales_order_line_id, DeliveryInstruction.status == FULFILLED)
    ):
        total += quantity
    return total


@dataclass(frozen=True)
class LinePosition:
    sales_order_line_id: int
    ordered_quantity: Decimal
    fulfilled_quantity: Decimal
    remaining_quantity: Decimal
    ceiling_quantity: Decimal
    remaining_permitted_quantity: Decimal


def line_position(db: Session, line: SalesOrderLine, allowance_percent: Decimal) -> LinePosition:
    fulfilled = fulfilled_quantity(db, line.id)
    top = ceiling(line.quantity, allowance_percent)
    return LinePosition(line.id, line.quantity, fulfilled, line.quantity - fulfilled, top, top - fulfilled)


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
