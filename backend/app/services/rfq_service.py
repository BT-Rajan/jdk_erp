"""RFQ business logic that doesn't belong inline in the API layer --
numbering, status-transition rules, response capture, decision recording,
and conversion into a Purchase Order (docs/modules/rfq.md). Mirrors
app/services/purchase_order_service.py's shape. Never commits -- the
caller commits alongside whatever audit_service.log_event call belongs
with the same change."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleError, ConflictError, ValidationError
from app.models.purchase_order import PurchaseOrder
from app.models.raw_material import RawMaterial
from app.models.rfq import (
    ALLOWED_STATUS_TRANSITIONS,
    CONVERTED,
    ISSUED,
    RESPONSE_RECEIVED,
    SELECTED,
    Rfq,
    RfqResponse,
)
from app.services import purchase_order_service

_MAX_YEARLY_SEQUENCE = 9999


def generate_rfq_number(db: Session, organisation_id: int, today: date | None = None) -> str:
    """`YY3NNNN` -- 2-digit year, fixed RFQ-type digit `3`, 4-digit
    sequence that resets every calendar year (docs/modules/rfq.md #7).
    Counts existing RFQs for this organisation whose number already
    starts with this year's `YY3` prefix -- the same count-and-retry
    discipline every other code generator in this codebase uses, just
    scoped by year (docs/audit/RFQ_AUDIT.md #2)."""
    today = today or date.today()
    prefix = f"{today.year % 100:02d}3"
    existing = db.query(Rfq).filter(Rfq.organisation_id == organisation_id, Rfq.rfq_number.like(f"{prefix}%")).count()
    sequence = existing + 1
    if sequence > _MAX_YEARLY_SEQUENCE:
        raise ConflictError("This organisation has reached the maximum number of RFQs for this year.")
    return f"{prefix}{sequence:04d}"


def assert_transition_allowed(current_status: str, target_status: str) -> None:
    allowed = ALLOWED_STATUS_TRANSITIONS.get(current_status, set())
    if target_status not in allowed:
        raise BusinessRuleError(f"Cannot change RFQ status from '{current_status}' to '{target_status}'.")


def capture_response(
    db: Session, *, rfq: Rfq, response_received_at: datetime, note: str | None, created_by_user_id: int | None
) -> RfqResponse:
    """docs/modules/rfq.md #5. Only valid once an RFQ has actually been
    issued. The first captured response moves `issued -> response_received`
    as a side effect -- never a direct status-change target, the same
    discipline docs/modules/purchase_orders.md #4 established for
    partially_received/fully_received. A later response on an already
    response_received RFQ (a revised quote) is a new row, no status
    change needed."""
    if rfq.status not in (ISSUED, RESPONSE_RECEIVED):
        raise BusinessRuleError("Can only capture a supplier response for an issued RFQ.")

    response = RfqResponse(
        organisation_id=rfq.organisation_id,
        rfq_id=rfq.id,
        response_received_at=response_received_at,
        note=note,
        created_by_user_id=created_by_user_id,
    )
    db.add(response)
    db.flush()

    if rfq.status == ISSUED:
        rfq.status = RESPONSE_RECEIVED
        db.add(rfq)
    return response


def decide(
    db: Session,
    *,
    rfq: Rfq,
    decision: str,
    selected_response_id: int | None,
    decision_note: str | None,
    decided_by_user_id: int | None,
) -> None:
    """docs/modules/rfq.md #6 -- only valid from response_received.
    `selected_response_id` is required when selecting, and must reference
    a response that actually belongs to this RFQ."""
    if rfq.status != RESPONSE_RECEIVED:
        raise BusinessRuleError("A decision can only be made once a supplier response has been received.")

    if decision == SELECTED:
        if selected_response_id is None:
            raise ValidationError(
                "selected_response_id is required when selecting a response.",
                fields={"selected_response_id": "Required when decision is 'selected'."},
            )
        response = (
            db.query(RfqResponse)
            .filter(RfqResponse.id == selected_response_id, RfqResponse.rfq_id == rfq.id)
            .first()
        )
        if response is None:
            raise ValidationError(
                "selected_response_id must reference a response captured on this RFQ.",
                fields={"selected_response_id": "Not a response on this RFQ."},
            )
        rfq.selected_response_id = response.id

    rfq.status = decision
    rfq.decided_by_user_id = decided_by_user_id
    rfq.decided_at = datetime.utcnow()
    rfq.decision_note = decision_note
    db.add(rfq)


@dataclass
class RfqConversionLine:
    raw_material: RawMaterial
    quantity: Decimal
    unit_price: Decimal


def convert_to_purchase_order(
    db: Session,
    *,
    rfq: Rfq,
    warehouse_id: int,
    lines: list[RfqConversionLine],
) -> PurchaseOrder:
    """docs/modules/rfq.md #8/#12 -- only valid from `selected`. Supplier
    and each line's material/quantity are carried forward from the RFQ
    untouched; `warehouse_id` and each line's `unit_price` are the only
    new input (never captured as structured data anywhere upstream).
    Built on the same app/services/purchase_order_service.
    create_purchase_order_with_lines the plain "New Purchase" flow uses
    (docs/audit/RFQ_AUDIT.md #5) -- one transaction, caller commits.
    Moving to `converted` here is also this action's own idempotency
    guard: a repeated submission fails assert_transition_allowed before
    a second Purchase Order could ever be created."""
    assert_transition_allowed(rfq.status, CONVERTED)

    purchase_order = purchase_order_service.create_purchase_order_with_lines(
        db,
        organisation_id=rfq.organisation_id,
        supplier_id=rfq.supplier_id,
        warehouse_id=warehouse_id,
        order_date=date.today(),
        expected_delivery_date=rfq.required_delivery_date,
        notes=f"Converted from RFQ {rfq.rfq_number}.",
        rfq_id=rfq.id,
        lines=[
            purchase_order_service.PurchaseOrderLineInput(
                raw_material=line.raw_material, quantity=line.quantity, unit_price=line.unit_price
            )
            for line in lines
        ],
    )

    rfq.purchase_order_id = purchase_order.id
    rfq.status = CONVERTED
    db.add(rfq)
    return purchase_order
