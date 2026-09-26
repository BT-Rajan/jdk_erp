"""Delivery Instructions (Delivery D2): creating a shipment tranche of a
Sales Order. A Sales Order may be delivered in several tranches, so there
is no one-per-order limit.

Creation copies, per line, the Sales Order line's ordered quantity,
product and stock unit, the tranche quantity, and the organisation's
current Delivery Scrap Allowance %, and stores
max_permitted_quantity = quantity x (1 + allowance / 100) exactly -- so a
later change to the setting never alters an existing instruction.

Records only: nothing moves or reserves stock, changes the Sales Order,
counts pallets or checks payment. The caller checks the permission,
audits and commits."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.errors import ConflictError, ValidationError
from app.models.delivery_instruction import PENDING, DeliveryInstruction, DeliveryInstructionLine
from app.models.organisation import Organisation
from app.models.sales_order import HANDED_OFF, PARTIALLY_DELIVERED, SalesOrder
from app.services import document_numbering

DELIVERABLE_STATUSES = (HANDED_OFF, PARTIALLY_DELIVERED)
_HUNDRED = Decimal("100")


@dataclass(frozen=True)
class LineInput:
    sales_order_line_id: int
    quantity: Decimal


def max_permitted_quantity(quantity: Decimal, allowance_percent: Decimal) -> Decimal:
    """quantity x (1 + allowance / 100), exact -- no rounding."""
    return quantity * (_HUNDRED + allowance_percent) / _HUNDRED


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

    allowance = db.get(Organisation, order.organisation_id).delivery_scrap_allowance_percent

    def build(number: str) -> DeliveryInstruction:
        instruction = DeliveryInstruction(
            organisation_id=order.organisation_id,
            delivery_number=number,
            sales_order_id=order.id,
            customer_id=order.customer_id,
            status=PENDING,
            created_by_user_id=user_id,
        )
        instruction.lines = [
            DeliveryInstructionLine(
                sales_order_line_id=entry.sales_order_line_id,
                product_id=order_lines[entry.sales_order_line_id].product_id,
                unit_of_measure_id=order_lines[entry.sales_order_line_id].unit_of_measure_id,
                ordered_quantity=order_lines[entry.sales_order_line_id].quantity,
                quantity=entry.quantity,
                scrap_allowance_percent=allowance,
                max_permitted_quantity=max_permitted_quantity(entry.quantity, allowance),
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
