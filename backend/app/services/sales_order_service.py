"""Sales Orders (Sales S13), per the S13.1 decisions.

- convert: the owning salesman turns one ACCEPTED quotation into its
  Sales Order. Acceptance is the only prerequisite (no readiness,
  feasibility or price re-check). The order copies the quotation's
  commercial snapshot; the quotation becomes CONVERTED and is locked.
- cancel: the owning salesman or their team head, reason mandatory. There
  is no fulfilment hand-off state yet, so any open order can be cancelled.
- admin_update: only Admin, reason mandatory; lines are re-validated and
  re-priced exactly like quotation lines. The customer is the accepted
  quotation's and can never change (S13.5).

Authority is checked by the API layer; this module enforces state. It
reserves, produces, moves, bills and delivers nothing."""

from datetime import date, datetime

from sqlalchemy.orm import Session

from app.core.errors import ConflictError, ValidationError
from app.models.quotation import ACCEPTED, CONVERTED, Quotation
from app.models.sales_order import CANCELLED, OPEN, SalesOrder, SalesOrderLine
from app.services import document_numbering, quotation_service

_UNSET = object()


def convert(db: Session, quotation: Quotation, user_id: int, today: date) -> SalesOrder:
    """Creates the Sales Order from an accepted quotation and marks the
    quotation converted, in one flush. The caller audits and commits."""
    if quotation.status != ACCEPTED:
        raise ConflictError(f"Only an accepted quotation can be converted (this one is {quotation.status}).")

    def build(number: str) -> SalesOrder:
        order = SalesOrder(
            organisation_id=quotation.organisation_id,
            order_number=number,
            quotation_id=quotation.id,
            customer_id=quotation.customer_id,
            order_date=today,
            requested_delivery_date=quotation.requested_delivery_date,
            currency=quotation.currency,
            subtotal_amount=quotation.subtotal_amount,
            total_amount=quotation.total_amount,
            status=OPEN,
            created_by_user_id=user_id,
        )
        order.lines = [
            SalesOrderLine(
                line_number=line.line_number,
                product_id=line.product_id,
                quantity=line.quantity,
                unit_of_measure_id=line.unit_of_measure_id,
                unit_price=line.unit_price,
                line_amount=line.line_amount,
            )
            for line in quotation.lines
        ]
        return order

    order = document_numbering.insert_with_yearly_number(
        db,
        build=build,
        number_column=SalesOrder.order_number,
        organisation_column=SalesOrder.organisation_id,
        organisation_id=quotation.organisation_id,
        type_digit=document_numbering.SALES_ORDER_TYPE_DIGIT,
        today=today,
        label="sales order",
    )
    quotation.status = CONVERTED
    db.add(quotation)
    db.flush()
    return order


def cancel(order: SalesOrder, user_id: int, reason: str) -> None:
    """Cancels an open order with its mandatory reason. Final."""
    if order.status != OPEN:
        raise ConflictError(f"Only an open order can be cancelled (this one is {order.status}).")
    order.status = CANCELLED
    order.cancelled_at = datetime.utcnow()
    order.cancelled_by_user_id = user_id
    order.cancellation_reason = reason


def admin_update(
    db: Session,
    order: SalesOrder,
    *,
    today: date,
    customer_id: int | None = None,
    requested_delivery_date=_UNSET,
    lines: list[quotation_service.LineInput] | None = None,
) -> list[str]:
    """Admin's change to an open order (the reason is audited by the
    caller). Lines are replaced as a whole and re-priced/re-validated like
    quotation lines; the number, status, customer and source quotation
    never change. Returns the changed field names."""
    if order.status != OPEN:
        raise ConflictError(f"Only an open order can be changed (this one is {order.status}).")
    changed: list[str] = []
    if customer_id is not None and customer_id != order.customer_id:
        raise ValidationError(
            "The customer of a Sales Order cannot be changed.",
            fields={"customer_id": "Fixed to the source quotation's customer."},
        )
    if requested_delivery_date is not _UNSET and requested_delivery_date != order.requested_delivery_date:
        quotation_service.check_requested_date(requested_delivery_date, today)
        order.requested_delivery_date = requested_delivery_date
        changed.append("requested_delivery_date")
    if lines is not None:
        values = quotation_service.price_lines(db, order.organisation_id, lines, order.currency)
        old = [(l.product_id, l.quantity, l.unit_of_measure_id, l.unit_price) for l in order.lines]
        new = [(v["product_id"], v["quantity"], v["unit_of_measure_id"], v["unit_price"]) for v in values]
        if old != new:
            order.lines.clear()
            db.flush()
            order.lines = [
                SalesOrderLine(
                    line_number=v["line_number"],
                    product_id=v["product_id"],
                    quantity=v["quantity"],
                    unit_of_measure_id=v["unit_of_measure_id"],
                    unit_price=v["unit_price"],
                    line_amount=v["line_amount"],
                )
                for v in values
            ]
            subtotal = quotation_service.subtotal_of(values, order.currency)
            order.subtotal_amount = subtotal
            order.total_amount = subtotal
            changed.append("lines")
    db.add(order)
    db.flush()
    return changed
