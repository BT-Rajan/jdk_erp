"""Sales Orders (Sales S13, hand-off S14.2).

- convert: the owning salesman turns one ACCEPTED quotation into its
  Sales Order, which is handed off to fulfilment automatically at that
  moment (S14.2). Creation is refused unless every hand-off prerequisite
  holds: the customer has a phone number, an address and an
  Admin-set payment arrangement (no payment needs to be received), and
  the quotation's readiness (S9) is `ready` -- requested date not past,
  prices in range or Admin-approved, feasibility current and acceptable.
  The order copies the quotation's commercial snapshot; the quotation
  becomes CONVERTED and is locked. At the same hand-off each line's
  fulfilment is assessed and any Finished Goods shortfall becomes a
  Production Requirement (production_requirement_service, S15.2).
- cancel: Admin only after hand-off, reason mandatory.
- admin_update: Admin only, reason mandatory; the requested date,
  quantities and prices may change -- never the customer (S13.5),
  products or units. A line's quantity cannot change once its
  fulfilment was assessed; Admin must resolve that first (S15.1).
  Returns every change as old -> new for the audit.

Authority is checked by the API layer; this module enforces state. The
order is fulfilment's source of truth, but this module reserves,
produces, moves, bills and delivers nothing."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.errors import ConflictError, ValidationError
from app.models.quotation import ACCEPTED, CONVERTED, Quotation
from app.models.sales_order import CANCELLED, HANDED_OFF, HANDOFF_AUTOMATIC, SalesOrder, SalesOrderLine
from app.services import (
    document_numbering,
    fg_allocation_service,
    production_requirement_service,
    quotation_readiness_service,
    quotation_service,
)

_UNSET = object()


def check_handoff_prerequisites(db: Session, quotation: Quotation, now: datetime) -> quotation_readiness_service.Readiness:
    """The S14.2 hand-off prerequisites, all from existing data: customer
    phone, address and payment arrangement, then the quotation's current
    readiness (the one S9 gate -- no second feasibility or price check)."""
    customer = quotation.customer
    missing = {}
    if not (customer.phone or "").strip():
        missing["phone"] = "The customer needs a phone number."
    if not (customer.address or "").strip():
        missing["address"] = "The customer needs an address."
    if customer.payment_arrangement is None:
        missing["payment_arrangement"] = "Admin must set the customer's payment arrangement."
    if missing:
        raise ValidationError("The customer is not ready for a Sales Order: " + " ".join(missing.values()), fields=missing)
    readiness = quotation_readiness_service.assess(db, quotation, now)
    if readiness.status != quotation_readiness_service.READY:
        raise ConflictError(
            f"The quotation is not ready for a Sales Order ({readiness.status}: {', '.join(readiness.reason_codes)})."
        )
    return readiness


_ZERO = Decimal("0")


def convert(db: Session, quotation: Quotation, user_id: int, now: datetime) -> SalesOrder:
    """Creates the Sales Order from an accepted quotation, handed off to
    fulfilment automatically, and marks the quotation converted, in one
    flush. `now` is Kuwait time. The caller audits and commits."""
    if quotation.status != ACCEPTED:
        raise ConflictError(f"Only an accepted quotation can be converted (this one is {quotation.status}).")
    check_handoff_prerequisites(db, quotation, now)
    today = now.date()

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
            status=HANDED_OFF,
            created_by_user_id=user_id,
            handed_off_at=datetime.utcnow(),
            handed_off_by_user_id=user_id,
            handoff_source=HANDOFF_AUTOMATIC,
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
    production_requirement_service.create_for_order(db, order)
    return order


def cancel(order: SalesOrder, user_id: int, reason: str) -> None:
    """Cancels a handed-off order with its mandatory reason. Final. What
    this means downstream is for those modules to handle."""
    if order.status != HANDED_OFF:
        raise ConflictError(f"Only a handed-off order can be cancelled (this one is {order.status}).")
    order.status = CANCELLED
    order.cancelled_at = datetime.utcnow()
    order.cancelled_by_user_id = user_id
    order.cancellation_reason = reason


def _plain(value) -> str:
    """A Decimal without trailing zeros, for the audit trail."""
    return format(value.normalize(), "f")


def admin_update(
    db: Session,
    order: SalesOrder,
    *,
    today,
    customer_id: int | None = None,
    requested_delivery_date=_UNSET,
    lines: list[quotation_service.LineInput] | None = None,
    confirm_fulfilment_change: bool = False,
) -> tuple[list[str], list[production_requirement_service.RequirementChange], list[fg_allocation_service.AllocationChange]]:
    """Admin's change to a handed-off order (the reason is audited by the
    caller): the requested date, and each line's quantity and unit price,
    re-validated and re-priced like quotation lines. The customer,
    products, units, line count, number, status and source quotation never
    change. Returns every change as "field: old -> new" (empty if
    nothing changed), and the Production Requirement and FG allocation
    changes it caused.

    A quantity change on a line already assessed at hand-off is refused
    unless the Admin confirms it (`confirm_fulfilment_change`, Production
    P1). Then, in this one operation: any FG claim above the new quantity
    returns to free stock, and the line's Production Requirement follows
    ordered - delivered - allocated (production_requirement_service.
    recalculate_line). The hand-off assessment is never rewritten. A
    handed-off order has nothing delivered yet."""
    if order.status != HANDED_OFF:
        raise ConflictError(f"Only a handed-off order can be changed (this one is {order.status}).")
    if customer_id is not None and customer_id != order.customer_id:
        raise ValidationError(
            "The customer of a Sales Order cannot be changed.",
            fields={"customer_id": "Fixed to the source quotation's customer."},
        )
    changes: list[str] = []
    requirement_changes: list[production_requirement_service.RequirementChange] = []
    allocation_changes: list[fg_allocation_service.AllocationChange] = []
    if requested_delivery_date is not _UNSET and requested_delivery_date != order.requested_delivery_date:
        quotation_service.check_requested_date(requested_delivery_date, today)
        changes.append(f"requested_delivery_date: {order.requested_delivery_date} -> {requested_delivery_date}")
        order.requested_delivery_date = requested_delivery_date
    if lines is not None:
        values = quotation_service.price_lines(db, order.organisation_id, lines, order.currency)
        same_products = len(values) == len(order.lines) and all(
            (v["product_id"], v["unit_of_measure_id"]) == (line.product_id, line.unit_of_measure_id)
            for v, line in zip(values, order.lines)
        )
        if not same_products:
            raise ValidationError(
                "Only quantities and prices can change on a Sales Order; its products and units are fixed.",
                fields={"lines": "Keep every line's product and unit, in order."},
            )
        assessed = production_requirement_service.lines_with_fulfilment(db, order)
        affected = [line.line_number for v, line in zip(values, order.lines) if v["quantity"] != line.quantity and line.id in assessed]
        if affected and not confirm_fulfilment_change:
            raise ConflictError(
                "The quantity of line(s) "
                + ", ".join(str(n) for n in affected)
                + " was already assessed for fulfilment (stock / production requirement). "
                "Confirm the production demand change to go ahead; dates and prices can change without it."
            )
        for v, line in zip(values, order.lines):
            if v["quantity"] != line.quantity:
                changes.append(f"line {line.line_number} quantity: {_plain(line.quantity)} -> {_plain(v['quantity'])}")
                line.quantity = v["quantity"]
                if line.id in assessed:
                    clamped = fg_allocation_service.clamp_to_line(db, line, _ZERO, "Sales Order line quantity reduced")
                    if clamped is not None:
                        allocation_changes.append(clamped)
                    change = production_requirement_service.recalculate_line(db, order, line, _ZERO)
                    if change is not None:
                        requirement_changes.append(change)
            if v["unit_price"] != line.unit_price:
                changes.append(f"line {line.line_number} unit_price: {_plain(line.unit_price)} -> {_plain(v['unit_price'])}")
                line.unit_price = v["unit_price"]
            line.line_amount = v["line_amount"]
        subtotal = quotation_service.subtotal_of(values, order.currency)
        if subtotal != order.total_amount:
            changes.append(f"total_amount: {_plain(order.total_amount)} -> {_plain(subtotal)} {order.currency}")
        order.subtotal_amount = subtotal
        order.total_amount = subtotal
    db.add(order)
    db.flush()
    return changes, requirement_changes, allocation_changes
