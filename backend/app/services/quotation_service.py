"""Quotation data foundation (Sales S4): creating a draft quotation with
server-calculated amounts and price-range checks. Access is decided by
the caller (app/api/quotations.py) through customer_scope before this
runs; nothing here reserves stock, touches inventory, production or
payment, or moves a quotation beyond draft."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.currency import DEFAULT_CURRENCY, round_currency
from app.core.errors import ConflictError, ValidationError
from app.models.product import Product
from app.models.quotation import DRAFT, Quotation, QuotationLine
from app.services import document_numbering


@dataclass(frozen=True)
class LineInput:
    product_id: int
    quantity: Decimal
    unit_of_measure_id: int
    unit_price: Decimal


def price_needs_approval(unit_price: Decimal, min_price: Decimal | None, max_price: Decimal | None) -> bool:
    """A price needs Admin approval unless the product has a full
    permitted range (both bounds) and the price lies within it. A product
    with no range -- or only one bound -- needs approval for any price
    (business decision, Sales S4)."""
    if min_price is None or max_price is None:
        return True
    return not (min_price <= unit_price <= max_price)


def _resolve_product(db: Session, organisation_id: int, line: LineInput, index: int) -> Product:
    product = (
        db.query(Product)
        .filter(Product.id == line.product_id, Product.organisation_id == organisation_id, Product.is_active.is_(True))
        .first()
    )
    if product is None:
        raise ValidationError(
            f"Line {index}: product not found or inactive.",
            fields={f"lines.{index}.product_id": "Not an active product in your organisation."},
        )
    if line.unit_of_measure_id != product.unit_of_measure_id:
        raise ValidationError(
            f"Line {index}: the unit must be the product's own unit -- no conversion is applied.",
            fields={f"lines.{index}.unit_of_measure_id": "Must be the product's own unit of measure."},
        )
    return product


def _check_requested_date(requested_delivery_date: date | None, today: date) -> None:
    if requested_delivery_date is not None and requested_delivery_date < today:
        raise ValidationError(
            "The requested delivery date is in the past.",
            fields={"requested_delivery_date": "Must be today or later."},
        )


def _price_lines(db: Session, organisation_id: int, lines: list[LineInput], currency: str) -> list[dict]:
    """Validates every line and derives its amount and price flags -- the
    one place both create and edit price lines."""
    line_values: list[dict] = []
    for index, line in enumerate(lines, start=1):
        product = _resolve_product(db, organisation_id, line, index)
        line_values.append(
            {
                "line_number": index,
                "product_id": product.id,
                "quantity": line.quantity,
                "unit_of_measure_id": product.unit_of_measure_id,
                "unit_price": line.unit_price,
                "line_amount": round_currency(line.quantity * line.unit_price, currency),
                "min_selling_price": product.min_selling_price,
                "max_selling_price": product.max_selling_price,
                "price_approval_required": price_needs_approval(
                    line.unit_price, product.min_selling_price, product.max_selling_price
                ),
            }
        )
    return line_values


def _subtotal(line_values: list[dict], currency: str) -> Decimal:
    return round_currency(sum((values["line_amount"] for values in line_values), Decimal("0")), currency)


def create_quotation(
    db: Session,
    *,
    organisation_id: int,
    customer_id: int,
    created_by_user_id: int,
    quotation_date: date,
    lines: list[LineInput],
    requested_delivery_date: date | None = None,
    currency: str = DEFAULT_CURRENCY,
) -> Quotation:
    """`requested_delivery_date`, if given, must not be before
    `quotation_date`; it is stored exactly as requested. Validates every
    line, then inserts the numbered header with its
    lines in one flush. Amounts are always derived here, from quantity x
    unit price rounded to the currency's minor unit; nothing the client
    sends about amounts is read. The caller commits."""
    _check_requested_date(requested_delivery_date, quotation_date)
    line_values = _price_lines(db, organisation_id, lines, currency)
    subtotal = _subtotal(line_values, currency)

    def build(number: str) -> Quotation:
        quotation = Quotation(
            organisation_id=organisation_id,
            quotation_number=number,
            customer_id=customer_id,
            created_by_user_id=created_by_user_id,
            quotation_date=quotation_date,
            status=DRAFT,
            currency=currency,
            subtotal_amount=subtotal,
            total_amount=subtotal,
            price_approval_required=any(values["price_approval_required"] for values in line_values),
            requested_delivery_date=requested_delivery_date,
        )
        quotation.lines = [QuotationLine(**values) for values in line_values]
        return quotation

    return document_numbering.insert_with_yearly_number(
        db,
        build=build,
        number_column=Quotation.quotation_number,
        organisation_column=Quotation.organisation_id,
        organisation_id=organisation_id,
        type_digit=document_numbering.QUOTATION_TYPE_DIGIT,
        today=quotation_date,
        label="quotation",
    )


_UNSET = object()


def update_quotation(
    db: Session,
    quotation: Quotation,
    *,
    today: date,
    customer_id: int | None = None,
    requested_delivery_date=_UNSET,
    lines: list[LineInput] | None = None,
) -> list[str]:
    """Controlled edit of a draft quotation (Sales S10). Only the fields
    passed change; lines are replaced as a whole and re-priced and
    re-validated exactly like creation. The number, date, status,
    currency, owner and amounts are never taken from the caller. Returns
    the names of the fields that changed; the caller audits and commits.

    A change to customer, requested date or lines makes any earlier
    feasibility result stale automatically (feasibility_record_service.
    is_current compares against these inputs)."""
    if quotation.status != DRAFT:
        raise ConflictError("Only a draft quotation can be edited.")
    changed: list[str] = []

    if customer_id is not None and customer_id != quotation.customer_id:
        quotation.customer_id = customer_id
        changed.append("customer")

    if requested_delivery_date is not _UNSET and requested_delivery_date != quotation.requested_delivery_date:
        _check_requested_date(requested_delivery_date, today)
        quotation.requested_delivery_date = requested_delivery_date
        changed.append("requested_delivery_date")

    if lines is not None:
        line_values = _price_lines(db, quotation.organisation_id, lines, quotation.currency)
        old = [(l.product_id, l.quantity, l.unit_of_measure_id, l.unit_price) for l in quotation.lines]
        new = [(v["product_id"], v["quantity"], v["unit_of_measure_id"], v["unit_price"]) for v in line_values]
        if old != new:
            quotation.lines.clear()
            db.flush()
            quotation.lines = [QuotationLine(**values) for values in line_values]
            subtotal = _subtotal(line_values, quotation.currency)
            quotation.subtotal_amount = subtotal
            quotation.total_amount = subtotal
            quotation.price_approval_required = any(v["price_approval_required"] for v in line_values)
            changed.append("lines")
            if quotation.price_decision is not None:
                # The decision was about the old prices.
                quotation.price_decision = None
                quotation.price_decision_reason = None
                quotation.price_decision_by_user_id = None
                quotation.price_decision_at = None
                changed.append("price_decision_cleared")

    db.add(quotation)
    db.flush()
    return changed


def decide_price(db: Session, quotation: Quotation, decision: str, reason: str, user_id: int) -> str | None:
    """Admin's approve/reject of the quotation's prices (Sales S11.1) --
    only while some line needs price approval, i.e. is outside its
    product's permitted range or the product has no full range. Same
    shape as the S8 feasibility decision; an existing decision is
    replaced the same way S8 allows. Returns the previous decision; the
    caller audits and commits."""
    if not quotation.price_approval_required:
        raise ConflictError("No line on this quotation needs price approval.")
    previous = quotation.price_decision
    quotation.price_decision = decision
    quotation.price_decision_reason = reason
    quotation.price_decision_by_user_id = user_id
    quotation.price_decision_at = datetime.utcnow()
    db.add(quotation)
    return previous
