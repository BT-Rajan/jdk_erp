"""The one `YY?NNNN` document-number mechanism: 2-digit year + a fixed
one-digit document type + a 4-digit per-organisation sequence that
resets every calendar year. RFQ, Purchase Order, PO Payment and Goods
Receipt already number this way (each through a thin wrapper that
delegates here); future Sales documents (Quotation, Sales Order,
Delivery Note) use the same two functions below rather than a copy of
any of them.

How uniqueness is guaranteed -- the same proven discipline those four
documents already rely on:
1. `next_yearly_number` proposes count-of-this-year's-numbers + 1 for
   the organisation. It never reserves anything, so opening a form or
   previewing a number allocates nothing.
2. The numbered table carries a DB unique constraint on
   (organisation_id, <number column>); that constraint, not the count,
   is what makes a duplicate impossible.
3. `insert_with_yearly_number` inserts the row; if a concurrent request
   took the same number first, the constraint rejects it and the insert
   is retried with a freshly counted number.

Numbered documents are never hard-deleted -- cancellation is a status --
so the count never goes down and an issued number is never handed out
again. A number is written once, on insert; nothing here updates it.

Document-type digits are business decisions, not something this module
invents. `ESTABLISHED_TYPE_DIGITS` records the ones already in use so a
new document type can't collide with them. Quotation is `4` (business
decision, Sales S4) and Sales Order `6` (Sales S13.1); the Delivery Note
digit is not defined yet -- an open business decision."""

from collections.abc import Callable
from datetime import date

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ConflictError
from app.core.timezone import now_jdk
from app.core.database import savepoint

MAX_YEARLY_SEQUENCE = 9999
MAX_INSERT_ATTEMPTS = 5

RFQ_TYPE_DIGIT = "3"
PURCHASE_ORDER_TYPE_DIGIT = "5"
PURCHASE_ORDER_PAYMENT_TYPE_DIGIT = "7"
GOODS_RECEIPT_TYPE_DIGIT = "9"
QUOTATION_TYPE_DIGIT = "4"
SALES_ORDER_TYPE_DIGIT = "6"

ESTABLISHED_TYPE_DIGITS = {
    RFQ_TYPE_DIGIT: "RFQ",
    PURCHASE_ORDER_TYPE_DIGIT: "Purchase Order",
    PURCHASE_ORDER_PAYMENT_TYPE_DIGIT: "Purchase Order Payment",
    GOODS_RECEIPT_TYPE_DIGIT: "Goods Receipt",
    QUOTATION_TYPE_DIGIT: "Quotation",
    SALES_ORDER_TYPE_DIGIT: "Sales Order",
}


def yearly_prefix(type_digit: str, today: date) -> str:
    if len(type_digit) != 1 or not type_digit.isdigit():
        raise ValueError("type_digit must be a single digit 0-9")
    return f"{today.year % 100:02d}{type_digit}"


def next_yearly_number(
    db: Session,
    *,
    number_column,
    organisation_column,
    organisation_id: int,
    type_digit: str,
    today: date | None = None,
    limit_message: str = "This organisation has reached the maximum number of documents for this year.",
) -> str:
    """The next `YY?NNNN` for this organisation, type and year. `today`
    defaults to the Kuwait calendar date; pass it explicitly to keep a
    caller's existing date source."""
    prefix = yearly_prefix(type_digit, today or now_jdk().date())
    existing = (
        db.query(number_column)
        .filter(organisation_column == organisation_id, number_column.like(f"{prefix}%"))
        .count()
    )
    sequence = existing + 1
    if sequence > MAX_YEARLY_SEQUENCE:
        raise ConflictError(limit_message)
    return f"{prefix}{sequence:04d}"


def insert_with_yearly_number(
    db: Session,
    *,
    build: Callable[[str], object],
    number_column,
    organisation_column,
    organisation_id: int,
    type_digit: str,
    today: date | None = None,
    label: str = "document",
):
    """Builds the row with `build(number)`, adds and flushes it, and
    retries with a newly counted number if the unique constraint says
    that number was just taken. Returns the flushed row; the caller
    commits. Each attempt runs in its own SAVEPOINT, so a retry never
    discards other work already done in the caller's transaction."""
    last_error: IntegrityError | None = None
    for _ in range(MAX_INSERT_ATTEMPTS):
        number = next_yearly_number(
            db,
            number_column=number_column,
            organisation_column=organisation_column,
            organisation_id=organisation_id,
            type_digit=type_digit,
            today=today,
            limit_message=f"This organisation has reached the maximum number of {label}s for this year.",
        )
        row = build(number)
        try:
            # A SAVEPOINT: a collision undoes only this insert, never earlier
            # work in the caller's transaction.
            with savepoint(db):
                db.add(row)
                db.flush()
            return row
        except IntegrityError as exc:
            last_error = exc
    raise ConflictError(f"Could not generate a unique {label} number. Please try again.") from last_error
