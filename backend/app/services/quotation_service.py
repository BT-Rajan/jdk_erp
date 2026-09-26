"""Quotation data foundation (Sales S4): creating a draft quotation with
server-calculated amounts and price-range checks. Access is decided by
the caller (app/api/quotations.py) through customer_scope before this
runs; nothing here reserves stock, touches inventory, production or
payment, or moves a quotation beyond draft."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.currency import DEFAULT_CURRENCY, round_currency
from app.core.errors import ValidationError
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


def create_quotation(
    db: Session,
    *,
    organisation_id: int,
    customer_id: int,
    created_by_user_id: int,
    quotation_date: date,
    lines: list[LineInput],
    currency: str = DEFAULT_CURRENCY,
) -> Quotation:
    """Validates every line, then inserts the numbered header with its
    lines in one flush. Amounts are always derived here, from quantity x
    unit price rounded to the currency's minor unit; nothing the client
    sends about amounts is read. The caller commits."""
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

    subtotal = round_currency(sum((values["line_amount"] for values in line_values), Decimal("0")), currency)

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
