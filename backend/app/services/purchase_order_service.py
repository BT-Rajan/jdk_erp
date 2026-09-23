"""Purchase Order business logic that doesn't belong inline in the API
layer -- creation, status-transition rules, price/total snapshotting, the
issue/revision, supplier-confirmation and receiving actions
(docs/modules/purchase_orders.md). Mirrors app/services/bom_service.py's
split: pure/validating helpers plus actions with real side effects,
called from app/api/purchase_orders.py and (for
create_purchase_order_with_lines) app/api/rfqs.py's convert-to-PO action
(docs/modules/rfq.md #8). Never commits -- the caller commits alongside
whatever audit_service.log_event call belongs with the same change."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleError, ConflictError, ValidationError
from app.models.inventory import PURCHASE_ORDER_RECEIPT_LINE_REFERENCE
from app.models.purchase_order import (
    ALLOWED_RECEIPT_STATUS_TRANSITIONS,
    ALLOWED_STATUS_TRANSITIONS,
    DRAFT,
    FULLY_RECEIVED,
    ISSUED,
    PARTIALLY_RECEIVED,
    PAYMENT_CANCELLED,
    PAYMENT_RECORDED,
    RECEIPT_CANCELLED,
    RECEIPT_DRAFT,
    RECEIPT_POSTED,
    RECEIPT_REVERSED,
    SUPPLIER_CONFIRMED,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderPayment,
    PurchaseOrderReceipt,
    PurchaseOrderReceiptLine,
    PurchaseOrderRevision,
    PurchaseOrderRevisionLine,
)
from app.models.raw_material import RawMaterial
from app.services import inventory_service

_MAX_CODE_ATTEMPTS = 5
_MAX_YEARLY_SEQUENCE = 9999
_MAX_YEARLY_PAYMENT_SEQUENCE = 9999
_MAX_YEARLY_RECEIPT_SEQUENCE = 9999
# docs/modules/purchase_orders.md #39 -- only a supplier-confirmed or
# already-partially-received PO can have a receipt drafted or posted
# against it, the same gate the removed receive_lines action used.
_RECEIVABLE_STATUSES = (SUPPLIER_CONFIRMED, PARTIALLY_RECEIVED)
# docs/modules/purchase_orders.md #30 -- a payment is only meaningful
# once a real commercial commitment exists (issued) and while the PO
# isn't already cancelled; DRAFT's total can still change before issue.
_PAYABLE_STATUSES = (ISSUED, SUPPLIER_CONFIRMED, PARTIALLY_RECEIVED, FULLY_RECEIVED)


@dataclass
class PurchaseOrderLineInput:
    raw_material: RawMaterial
    quantity: Decimal
    unit_price: Decimal | None = None


def assert_transition_allowed(current_status: str, target_status: str) -> None:
    """Every transition not in ALLOWED_STATUS_TRANSITIONS is rejected --
    fully_received/partially_received are valid statuses but never a
    direct target of this check (docs/modules/purchase_orders.md #23);
    they're only ever reached via receive_lines's own status recompute."""
    allowed = ALLOWED_STATUS_TRANSITIONS.get(current_status, set())
    if target_status not in allowed:
        raise BusinessRuleError(f"Cannot change purchase order status from '{current_status}' to '{target_status}'.")


def resolve_unit_price(raw_material: RawMaterial, requested_price: Decimal | None) -> Decimal:
    """Defaults from RawMaterial.reference_cost when the caller doesn't
    supply one, reproducing jdk_clean's own real, evidenced behaviour
    (docs/audit/PROCUREMENT_AUDIT.md #3) -- rejected outright if neither
    is available, never silently priced at zero."""
    if requested_price is not None:
        return requested_price
    if raw_material.reference_cost is not None:
        return raw_material.reference_cost
    raise ValidationError(
        f"unit_price is required -- {raw_material.name} has no reference cost configured.",
        fields={"unit_price": "Required; this raw material has no reference cost to default from."},
    )


def compute_line_total(quantity: Decimal, unit_price: Decimal) -> Decimal:
    return (quantity * unit_price).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def generate_po_number(db: Session, organisation_id: int, today: date | None = None) -> str:
    """`YY5NNNN` -- 2-digit year, fixed PO-type digit `5`, 4-digit
    sequence resetting every calendar year, per organisation
    (docs/modules/purchase_orders.md #21) -- the exact same shape and
    mechanism as app/services/rfq_service.generate_rfq_number, reused for
    a second document type rather than reinvented."""
    today = today or date.today()
    prefix = f"{today.year % 100:02d}5"
    existing = (
        db.query(PurchaseOrder)
        .filter(PurchaseOrder.organisation_id == organisation_id, PurchaseOrder.po_number.like(f"{prefix}%"))
        .count()
    )
    sequence = existing + 1
    if sequence > _MAX_YEARLY_SEQUENCE:
        raise ConflictError("This organisation has reached the maximum number of purchase orders for this year.")
    return f"{prefix}{sequence:04d}"


def create_purchase_order_with_lines(
    db: Session,
    *,
    organisation_id: int,
    supplier_id: int,
    warehouse_id: int,
    order_date: date,
    expected_delivery_date: date | None,
    notes: str | None,
    lines: list[PurchaseOrderLineInput],
    rfq_id: int | None = None,
) -> PurchaseOrder:
    """The one place a draft Purchase Order (with its lines) is created
    -- shared by app/api/purchase_orders.py's plain "New Purchase" flow
    and app/api/rfqs.py's convert-to-PO action (docs/audit/RFQ_AUDIT.md
    #5), so the two never maintain separate PO-creation logic. Caller has
    already validated supplier_id/warehouse_id are active and in this
    organisation, and resolved each line's RawMaterial the same way
    (docs/modules/purchase_orders.md #11) -- this function only handles
    the creation mechanics: numbering (with retry-on-IntegrityError,
    docs/modules/purchase_orders.md #21), price defaulting, and line-total
    snapshotting."""
    purchase_order: PurchaseOrder | None = None
    last_error: IntegrityError | None = None
    for _ in range(_MAX_CODE_ATTEMPTS):
        po_number = generate_po_number(db, organisation_id)
        purchase_order = PurchaseOrder(
            organisation_id=organisation_id,
            po_number=po_number,
            supplier_id=supplier_id,
            warehouse_id=warehouse_id,
            rfq_id=rfq_id,
            status=DRAFT,
            order_date=order_date,
            expected_delivery_date=expected_delivery_date,
            notes=notes,
        )
        db.add(purchase_order)
        try:
            db.flush()
            last_error = None
            break
        except IntegrityError as exc:
            db.rollback()
            last_error = exc
    if last_error is not None or purchase_order is None:
        raise ConflictError("Could not generate a unique purchase order number. Please try again.") from last_error

    for line_input in lines:
        unit_price = resolve_unit_price(line_input.raw_material, line_input.unit_price)
        db.add(
            PurchaseOrderLine(
                purchase_order_id=purchase_order.id,
                raw_material_id=line_input.raw_material.id,
                quantity=line_input.quantity,
                unit_price=unit_price,
                line_total=compute_line_total(line_input.quantity, unit_price),
            )
        )
    db.flush()
    return purchase_order


def total_amount(lines: list[PurchaseOrderLine]) -> Decimal:
    """Always derived from the lines' own snapshotted line_total, never a
    second stored header value that could drift (docs/modules/purchase_orders.md
    #2)."""
    total = Decimal("0")
    for line in lines:
        total += line.line_total
    return total


def issue_purchase_order(db: Session, *, purchase_order: PurchaseOrder, issued_by_user_id: int | None) -> PurchaseOrderRevision:
    """`draft -> issued` (docs/modules/purchase_orders.md #23/#24): snapshots
    the PO's current header/lines into a new, immutable
    PurchaseOrderRevision (`revision_number = purchase_order.revision_number
    + 1`) before flipping status. Requires at least one line, the same
    "cannot activate/confirm empty" gate every other lifecycle-advancing
    action in this codebase already has."""
    assert_transition_allowed(purchase_order.status, ISSUED)
    lines = db.query(PurchaseOrderLine).filter(PurchaseOrderLine.purchase_order_id == purchase_order.id).all()
    if not lines:
        raise BusinessRuleError("Cannot issue a purchase order with no lines.")

    next_revision_number = purchase_order.revision_number + 1
    revision = PurchaseOrderRevision(
        purchase_order_id=purchase_order.id,
        revision_number=next_revision_number,
        order_date=purchase_order.order_date,
        expected_delivery_date=purchase_order.expected_delivery_date,
        supplier_reference=purchase_order.supplier_reference,
        payment_terms=purchase_order.payment_terms,
        notes=purchase_order.notes,
        total_amount=total_amount(lines),
        issued_at=datetime.utcnow(),
        issued_by_user_id=issued_by_user_id,
    )
    db.add(revision)
    db.flush()

    for line in lines:
        db.add(
            PurchaseOrderRevisionLine(
                revision_id=revision.id,
                raw_material_id=line.raw_material_id,
                quantity=line.quantity,
                unit_price=line.unit_price,
                line_total=line.line_total,
            )
        )

    purchase_order.status = ISSUED
    purchase_order.revision_number = next_revision_number
    db.add(purchase_order)
    db.flush()
    return revision


def confirm_supplier(db: Session, *, purchase_order: PurchaseOrder, note: str | None, confirmed_by_user_id: int | None) -> None:
    """`issued -> supplier_confirmed` (docs/modules/purchase_orders.md
    #25) -- a distinct event from issuing (docs/modules/purchase_orders.md
    #15/#23's "sent != confirmed" rule). Evidence attachment (`file_ids`)
    is handled by the API layer via file_service.attach_files, the same
    as RFQ response capture."""
    assert_transition_allowed(purchase_order.status, SUPPLIER_CONFIRMED)
    purchase_order.status = SUPPLIER_CONFIRMED
    purchase_order.supplier_confirmed_at = datetime.utcnow()
    purchase_order.supplier_confirmed_by_user_id = confirmed_by_user_id
    purchase_order.supplier_confirmation_note = note
    db.add(purchase_order)


def generate_receipt_number(db: Session, organisation_id: int, today: date | None = None) -> str:
    """`YY9NNNN` -- the fourth use of the same generator shape (RFQ `3`,
    PO `5`, Payment `7`), for Goods Receipt (docs/modules/purchase_orders.md
    #40)."""
    today = today or date.today()
    prefix = f"{today.year % 100:02d}9"
    existing = (
        db.query(PurchaseOrderReceipt)
        .filter(PurchaseOrderReceipt.organisation_id == organisation_id, PurchaseOrderReceipt.receipt_number.like(f"{prefix}%"))
        .count()
    )
    sequence = existing + 1
    if sequence > _MAX_YEARLY_RECEIPT_SEQUENCE:
        raise ConflictError("This organisation has reached the maximum number of goods receipts for this year.")
    return f"{prefix}{sequence:04d}"


def assert_receipt_transition_allowed(current_status: str, target_status: str) -> None:
    allowed = ALLOWED_RECEIPT_STATUS_TRANSITIONS.get(current_status, set())
    if target_status not in allowed:
        raise BusinessRuleError(f"Cannot change goods receipt status from '{current_status}' to '{target_status}'.")


def create_receipt(
    db: Session,
    *,
    purchase_order: PurchaseOrder,
    receipt_date: date,
    supplier_delivery_reference: str | None,
    notes: str | None,
    entries: list[tuple[int, Decimal]],
    created_by_user_id: int | None,
) -> PurchaseOrderReceipt:
    """docs/modules/purchase_orders.md #37/#39. `entries` is a list of
    (purchase_order_line_id, quantity) pairs, all belonging to
    `purchase_order`. Creates a `draft` receipt -- zero inventory effect
    yet (#38); the same remaining-quantity check the old receive_lines
    ran is applied here too, against currently-known state, purely for
    immediate user feedback -- post_receipt's own atomic conditional
    UPDATE is the one authoritative guard against over-receipt at posting
    time, when concurrent drafts could otherwise both believe the same
    quantity is still available."""
    if purchase_order.status not in _RECEIVABLE_STATUSES:
        raise BusinessRuleError("Only a supplier-confirmed or partially received purchase order can be received.")
    if not entries:
        raise ValidationError("At least one line must be received.")

    line_ids = [line_id for line_id, _ in entries]
    if len(set(line_ids)) != len(line_ids):
        raise ValidationError("Each purchase order line can only appear once per receipt.")

    lines_by_id = {
        line.id: line
        for line in db.query(PurchaseOrderLine)
        .filter(PurchaseOrderLine.purchase_order_id == purchase_order.id, PurchaseOrderLine.id.in_(line_ids))
        .all()
    }
    for line_id, quantity in entries:
        line = lines_by_id.get(line_id)
        if line is None:
            raise ValidationError("One or more lines do not belong to this purchase order.")
        if quantity <= 0:
            raise ValidationError("Received quantity must be greater than zero.")
        remaining = line.quantity - line.received_quantity
        if quantity > remaining:
            raise ValidationError(
                f"Cannot receive {quantity} for raw material #{line.raw_material_id} -- "
                f"only {remaining} remains outstanding on this line.",
                fields={"quantity": "Exceeds the remaining quantity on this purchase order line."},
            )

    receipt: PurchaseOrderReceipt | None = None
    last_error: IntegrityError | None = None
    for _ in range(_MAX_CODE_ATTEMPTS):
        receipt = PurchaseOrderReceipt(
            organisation_id=purchase_order.organisation_id,
            receipt_number=generate_receipt_number(db, purchase_order.organisation_id),
            purchase_order_id=purchase_order.id,
            warehouse_id=purchase_order.warehouse_id,
            receipt_date=receipt_date,
            status=RECEIPT_DRAFT,
            supplier_delivery_reference=supplier_delivery_reference,
            notes=notes,
            created_by_user_id=created_by_user_id,
        )
        db.add(receipt)
        try:
            db.flush()
            last_error = None
            break
        except IntegrityError as exc:
            db.rollback()
            last_error = exc
    if last_error is not None or receipt is None:
        raise ConflictError("Could not generate a unique receipt number. Please try again.") from last_error

    for line_id, quantity in entries:
        line = lines_by_id[line_id]
        db.add(
            PurchaseOrderReceiptLine(
                receipt_id=receipt.id,
                purchase_order_line_id=line.id,
                raw_material_id=line.raw_material_id,
                quantity=quantity,
            )
        )
    db.flush()
    return receipt


def post_receipt(db: Session, *, receipt: PurchaseOrderReceipt, purchase_order: PurchaseOrder, posted_by_user_id: int | None) -> None:
    """`draft -> posted` (docs/modules/purchase_orders.md #38) -- the one
    place a Goods Receipt turns into an inventory movement. The status
    flip is itself an atomic conditional UPDATE (`WHERE status = 'draft'`)
    so posting the same receipt twice -- double-click, retry, refresh --
    finds zero matching rows the second time and is rejected before any
    inventory effect could double-apply (docs/audit/PROCUREMENT_AUDIT.md
    Revision 4 #7). Each line then applies the exact same atomic
    "increment received_quantity, but never past the ordered quantity"
    guard the removed receive_lines action used."""
    rowcount = (
        db.query(PurchaseOrderReceipt)
        .filter(PurchaseOrderReceipt.id == receipt.id, PurchaseOrderReceipt.status == RECEIPT_DRAFT)
        .update(
            {"status": RECEIPT_POSTED, "posted_at": datetime.utcnow(), "posted_by_user_id": posted_by_user_id},
            synchronize_session=False,
        )
    )
    if not rowcount:
        raise BusinessRuleError("Only a draft goods receipt can be posted -- it may already be posted.")
    db.expire(receipt)

    receipt_lines = db.query(PurchaseOrderReceiptLine).filter(PurchaseOrderReceiptLine.receipt_id == receipt.id).all()
    for receipt_line in receipt_lines:
        po_line_rowcount = (
            db.query(PurchaseOrderLine)
            .filter(
                PurchaseOrderLine.id == receipt_line.purchase_order_line_id,
                PurchaseOrderLine.received_quantity + receipt_line.quantity <= PurchaseOrderLine.quantity,
            )
            .update(
                {"received_quantity": PurchaseOrderLine.received_quantity + receipt_line.quantity},
                synchronize_session=False,
            )
        )
        if not po_line_rowcount:
            raise ConflictError(
                "This purchase order line's remaining quantity changed since this receipt was drafted. "
                "Please review the receipt and try again."
            )

        inventory_service.receive_stock(
            db,
            organisation_id=purchase_order.organisation_id,
            raw_material_id=receipt_line.raw_material_id,
            warehouse_id=receipt.warehouse_id,
            quantity=receipt_line.quantity,
            reference_type=PURCHASE_ORDER_RECEIPT_LINE_REFERENCE,
            reference_id=receipt_line.id,
            created_by_user_id=posted_by_user_id,
        )

    db.flush()
    _recompute_status(db, purchase_order)


def cancel_receipt(db: Session, *, receipt: PurchaseOrderReceipt, cancelled_by_user_id: int | None) -> None:
    """`draft -> cancelled` (docs/modules/purchase_orders.md #38) -- a
    receipt discarded before posting; no inventory effect ever existed to
    undo."""
    assert_receipt_transition_allowed(receipt.status, RECEIPT_CANCELLED)
    receipt.status = RECEIPT_CANCELLED
    receipt.cancelled_at = datetime.utcnow()
    receipt.cancelled_by_user_id = cancelled_by_user_id
    db.add(receipt)


def reverse_receipt(
    db: Session,
    *,
    receipt: PurchaseOrderReceipt,
    purchase_order: PurchaseOrder,
    reason: str,
    reversed_by_user_id: int | None,
) -> None:
    """`posted -> reversed` (docs/modules/purchase_orders.md #38) -- the
    only way to correct a posted receipt: never a direct edit of its
    quantities. Creates one offsetting negative StockMovement per line
    and steps `received_quantity` back down by the same atomic-guard
    mechanism `post_receipt` uses, then recomputes PO status. The
    original receipt and its original line quantities are never
    modified."""
    assert_receipt_transition_allowed(receipt.status, RECEIPT_REVERSED)
    receipt_lines = db.query(PurchaseOrderReceiptLine).filter(PurchaseOrderReceiptLine.receipt_id == receipt.id).all()

    for receipt_line in receipt_lines:
        po_line_rowcount = (
            db.query(PurchaseOrderLine)
            .filter(
                PurchaseOrderLine.id == receipt_line.purchase_order_line_id,
                PurchaseOrderLine.received_quantity - receipt_line.quantity >= 0,
            )
            .update(
                {"received_quantity": PurchaseOrderLine.received_quantity - receipt_line.quantity},
                synchronize_session=False,
            )
        )
        if not po_line_rowcount:
            raise ConflictError(
                "This purchase order line's received quantity changed since this receipt was posted. "
                "Please review before reversing."
            )

        inventory_service.reverse_stock(
            db,
            organisation_id=purchase_order.organisation_id,
            raw_material_id=receipt_line.raw_material_id,
            warehouse_id=receipt.warehouse_id,
            quantity=receipt_line.quantity,
            reference_type=PURCHASE_ORDER_RECEIPT_LINE_REFERENCE,
            reference_id=receipt_line.id,
            created_by_user_id=reversed_by_user_id,
        )

    receipt.status = RECEIPT_REVERSED
    receipt.reversed_at = datetime.utcnow()
    receipt.reversed_by_user_id = reversed_by_user_id
    receipt.reversal_reason = reason
    db.add(receipt)
    db.flush()
    _recompute_status(db, purchase_order)


def _recompute_status(db: Session, purchase_order: PurchaseOrder) -> None:
    """Called after both post_receipt and reverse_receipt (Revision 4) --
    a reversal can bring every line's received_quantity back down to zero,
    which is not `partially_received` (nothing outstanding has actually
    been received); it reverts the PO to `supplier_confirmed`, the same
    status it was in before its first receipt."""
    lines = db.query(PurchaseOrderLine).filter(PurchaseOrderLine.purchase_order_id == purchase_order.id).all()
    if all(line.received_quantity >= line.quantity for line in lines):
        purchase_order.status = FULLY_RECEIVED
    elif any(line.received_quantity > 0 for line in lines):
        purchase_order.status = PARTIALLY_RECEIVED
    else:
        purchase_order.status = SUPPLIER_CONFIRMED
    db.add(purchase_order)


def generate_payment_number(db: Session, organisation_id: int, today: date | None = None) -> str:
    """`YY7NNNN` -- the same generator shape used twice already
    (RFQ's `3`, Purchase Order's `5`), extended with a third fixed digit
    (`7`) for this document type (docs/modules/purchase_orders.md #31)."""
    today = today or date.today()
    prefix = f"{today.year % 100:02d}7"
    existing = (
        db.query(PurchaseOrderPayment)
        .filter(PurchaseOrderPayment.organisation_id == organisation_id, PurchaseOrderPayment.payment_number.like(f"{prefix}%"))
        .count()
    )
    sequence = existing + 1
    if sequence > _MAX_YEARLY_PAYMENT_SEQUENCE:
        raise ConflictError("This organisation has reached the maximum number of payments for this year.")
    return f"{prefix}{sequence:04d}"


def paid_amount(payments: list[PurchaseOrderPayment]) -> Decimal:
    """Every non-cancelled payment counts -- a cancelled one stays
    visible in history (docs/modules/purchase_orders.md #33) but no
    longer counts toward what's actually been paid."""
    total = Decimal("0")
    for payment in payments:
        if payment.status != PAYMENT_CANCELLED:
            total += payment.amount
    return total


def record_payment(
    db: Session,
    *,
    purchase_order: PurchaseOrder,
    current_lines: list[PurchaseOrderLine],
    existing_payments: list[PurchaseOrderPayment],
    payment_date: date,
    amount: Decimal,
    payment_method: str | None,
    reference_number: str | None,
    notes: str | None,
    created_by_user_id: int | None,
) -> PurchaseOrderPayment:
    """docs/modules/purchase_orders.md #33 -- only valid once the PO has
    been issued (its total is no longer a moving target) and isn't
    cancelled. Rejects a payment that would push total recorded payments
    beyond the PO's *current* total_amount (docs/audit/PROCUREMENT_AUDIT.md
    Revision 3 #5 -- no overpayment tolerance, no audited evidence
    permits one). A plain validate-then-insert, not the atomic
    conditional-UPDATE receive_lines uses -- payments are human-paced,
    low-concurrency finance entries, not a high-contention counter, so
    that extra mechanism would be disproportionate here."""
    if purchase_order.status not in _PAYABLE_STATUSES:
        raise BusinessRuleError("Payments can only be recorded against an issued purchase order.")
    if amount <= 0:
        raise ValidationError("Payment amount must be greater than zero.")

    outstanding = total_amount(current_lines) - paid_amount(existing_payments)
    if amount > outstanding:
        raise ValidationError(
            f"Cannot record a payment of {amount} -- only {outstanding} remains outstanding on this purchase order.",
            fields={"amount": "Exceeds the outstanding amount."},
        )

    for _ in range(_MAX_CODE_ATTEMPTS):
        payment = PurchaseOrderPayment(
            organisation_id=purchase_order.organisation_id,
            payment_number=generate_payment_number(db, purchase_order.organisation_id),
            purchase_order_id=purchase_order.id,
            payment_date=payment_date,
            amount=amount,
            payment_method=payment_method,
            reference_number=reference_number,
            notes=notes,
            status=PAYMENT_RECORDED,
            created_by_user_id=created_by_user_id,
        )
        db.add(payment)
        try:
            db.flush()
            return payment
        except IntegrityError as exc:
            db.rollback()
            last_error = exc
    raise ConflictError("Could not generate a unique payment number. Please try again.") from last_error


def cancel_payment(db: Session, *, payment: PurchaseOrderPayment, reason: str, cancelled_by_user_id: int | None) -> None:
    """docs/modules/purchase_orders.md #33 -- never a hard delete or a
    soft-delete-from-view; the payment stays visible with its original
    amount, simply excluded from paid_amount going forward."""
    if payment.status == PAYMENT_CANCELLED:
        raise BusinessRuleError("This payment has already been cancelled.")
    payment.status = PAYMENT_CANCELLED
    payment.cancelled_at = datetime.utcnow()
    payment.cancelled_by_user_id = cancelled_by_user_id
    payment.cancellation_reason = reason
    db.add(payment)
