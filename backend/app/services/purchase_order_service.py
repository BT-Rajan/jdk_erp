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
from app.core.database import savepoint
from app.models.inventory import PURCHASE_ORDER_RECEIPT_LINE_REFERENCE
from app.models.warehouse import Warehouse
from app.models.purchase_order import (
    ALLOWED_RECEIPT_STATUS_TRANSITIONS,
    ALLOWED_STATUS_TRANSITIONS,
    APPROVED,
    CLOSED,
    DEFAULT_CURRENCY,
    DRAFT,
    FULFILMENT_STATUSES,
    PARTIALLY_RECEIVED,
    PAYMENT_CANCELLED,
    PAYMENT_RECONCILIATION,
    PAYMENT_RECORDED,
    PAYMENT_RESOLUTIONS,
    PENDING_APPROVAL,
    RECEIPT_RESOLUTIONS,
    RECONCILIATION_OPEN,
    RECONCILIATION_PAYMENT,
    RECONCILIATION_RECEIPT,
    RECONCILIATION_REQUIRED,
    RECONCILIATION_RESOLVED,
    RESOLVE_ACCEPT_PAID_AMOUNT,
    RESOLVE_ACCEPT_RECEIVED_QUANTITY,
    RESOLVE_CANCEL_REMAINING,
    RECEIPT_CANCELLED,
    RECEIPT_DRAFT,
    RECEIPT_POSTED,
    RECEIPT_REVERSED,
    RECEIVED,
    SENT,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderPayment,
    PurchaseOrderReceipt,
    PurchaseOrderReceiptLine,
    PurchaseOrderReconciliation,
    PurchaseOrderRevision,
    PurchaseOrderRevisionLine,
)
from app.models.raw_material import RawMaterial
from app.services import document_numbering, inventory_service

_MAX_CODE_ATTEMPTS = 5
# docs/modules/purchase_orders.md #39 -- goods can only be received
# against a PO that has been sent to the supplier.
_RECEIVABLE_STATUSES = (SENT, PARTIALLY_RECEIVED)
# docs/modules/purchase_orders.md #30 -- a payment is only meaningful
# once the PO is approved (its total is fixed), and never once it is
# closed or cancelled.
_PAYABLE_STATUSES = (APPROVED, SENT, PARTIALLY_RECEIVED, RECONCILIATION_REQUIRED, RECEIVED, PAYMENT_RECONCILIATION)

UNPAID = "unpaid"
PARTIALLY_PAID = "partially_paid"
PAID = "paid"


@dataclass
class PurchaseOrderLineInput:
    """`unit_of_measure_id` None -> the material's own unit (factor 1).
    Otherwise `conversion_factor` is `1 unit = factor material units`,
    already resolved by the caller (app/services/uom_conversion.py)."""

    raw_material: RawMaterial
    quantity: Decimal
    unit_price: Decimal | None = None
    unit_of_measure_id: int | None = None
    conversion_factor: Decimal = Decimal(1)
    required_by_date: date | None = None
    remarks: str | None = None
    # Which RFQ line this line was converted from -- None for a PO
    # raised directly with no RFQ (gap-fix: split sourcing).
    rfq_line_id: int | None = None


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
    return document_numbering.next_yearly_number(
        db,
        number_column=PurchaseOrder.po_number,
        organisation_column=PurchaseOrder.organisation_id,
        organisation_id=organisation_id,
        type_digit=document_numbering.PURCHASE_ORDER_TYPE_DIGIT,
        today=today or date.today(),
        limit_message="This organisation has reached the maximum number of purchase orders for this year.",
    )


def default_warehouse(db: Session, organisation_id: int) -> Warehouse:
    """JDK has one warehouse, so a PO never asks for a delivery location:
    goods are received into the organisation's active warehouse."""
    warehouse = (
        db.query(Warehouse)
        .filter(Warehouse.organisation_id == organisation_id, Warehouse.is_active.is_(True))
        .order_by(Warehouse.id)
        .first()
    )
    if warehouse is None:
        raise ValidationError("No active warehouse to receive into. Add one under Master Data > Warehouses first.")
    return warehouse


def create_purchase_order_with_lines(
    db: Session,
    *,
    organisation_id: int,
    supplier_id: int,
    order_date: date,
    expected_delivery_date: date | None,
    notes: str | None,
    lines: list[PurchaseOrderLineInput],
    rfq_id: int | None = None,
    rfq_response_id: int | None = None,
    payment_terms: str | None = None,
    supplier_reference: str | None = None,
    delivery_instructions: str | None = None,
    created_by_user_id: int | None = None,
) -> PurchaseOrder:
    """The one place a draft Purchase Order (with its lines) is created
    -- shared by app/api/purchase_orders.py's plain "New Purchase" flow
    and app/api/rfqs.py's convert-to-PO action (docs/audit/RFQ_AUDIT.md
    #5), so the two never maintain separate PO-creation logic. Caller has
    already validated supplier_id is active and in this
    organisation, and resolved each line's RawMaterial the same way
    (docs/modules/purchase_orders.md #11) -- this function only handles
    the creation mechanics: numbering (with retry-on-IntegrityError,
    docs/modules/purchase_orders.md #21), price defaulting, and line-total
    snapshotting."""
    warehouse_id = default_warehouse(db, organisation_id).id
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
            rfq_response_id=rfq_response_id,
            status=DRAFT,
            order_date=order_date,
            expected_delivery_date=expected_delivery_date,
            payment_terms=payment_terms,
            supplier_reference=supplier_reference,
            currency=DEFAULT_CURRENCY,
            delivery_instructions=delivery_instructions,
            notes=notes,
            created_by_user_id=created_by_user_id,
        )
        try:
            # A SAVEPOINT, not db.rollback(): a number collision undoes only
            # this insert, never other work already flushed in the same
            # transaction (same pattern as inventory_service._increment_inventory).
            with savepoint(db):
                db.add(purchase_order)
                db.flush()
            last_error = None
            break
        except IntegrityError as exc:
            last_error = exc
    if last_error is not None or purchase_order is None:
        raise ConflictError("Could not generate a unique purchase order number. Please try again.") from last_error

    for line_input in lines:
        unit_price = resolve_unit_price(line_input.raw_material, line_input.unit_price)
        db.add(
            PurchaseOrderLine(
                purchase_order_id=purchase_order.id,
                raw_material_id=line_input.raw_material.id,
                rfq_line_id=line_input.rfq_line_id,
                quantity=line_input.quantity,
                unit_of_measure_id=line_input.unit_of_measure_id or line_input.raw_material.unit_of_measure_id,
                conversion_factor=line_input.conversion_factor if line_input.unit_of_measure_id else Decimal(1),
                unit_price=unit_price,
                line_total=compute_line_total(line_input.quantity, unit_price),
                required_by_date=line_input.required_by_date,
                remarks=line_input.remarks,
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


def final_amount(purchase_order: PurchaseOrder, lines: list[PurchaseOrderLine]) -> Decimal:
    """What JDK finally owes: every line's ordered quantity less any
    cancelled remainder, at its agreed price, plus a creator-accepted
    payment adjustment (docs/modules/purchase_orders.md Revision 6)."""
    total = Decimal("0")
    for line in lines:
        total += compute_line_total(line.quantity - line.cancelled_quantity, line.unit_price)
    return total + purchase_order.amount_adjustment


def _lines(db: Session, purchase_order: PurchaseOrder) -> list[PurchaseOrderLine]:
    return (
        db.query(PurchaseOrderLine)
        .filter(PurchaseOrderLine.purchase_order_id == purchase_order.id)
        .order_by(PurchaseOrderLine.id)
        .all()
    )


def _paid(db: Session, purchase_order: PurchaseOrder) -> Decimal:
    return paid_amount(
        db.query(PurchaseOrderPayment).filter(PurchaseOrderPayment.purchase_order_id == purchase_order.id).all()
    )


def _open_reconciliations(db: Session, purchase_order: PurchaseOrder) -> list[PurchaseOrderReconciliation]:
    return (
        db.query(PurchaseOrderReconciliation)
        .filter(
            PurchaseOrderReconciliation.purchase_order_id == purchase_order.id,
            PurchaseOrderReconciliation.status == RECONCILIATION_OPEN,
        )
        .all()
    )


def _open(db: Session, purchase_order: PurchaseOrder, kind: str, discrepancy: str) -> None:
    """Returns the PO to its creator -- one open reconciliation per kind."""
    if any(rec.kind == kind for rec in _open_reconciliations(db, purchase_order)):
        return
    db.add(PurchaseOrderReconciliation(purchase_order_id=purchase_order.id, kind=kind, discrepancy=discrepancy))
    db.flush()


def _fmt(value: Decimal) -> str:
    return f"{value.normalize():,f}"


def check_receipt_discrepancy(db: Session, purchase_order: PurchaseOrder, material_names: dict[int, str]) -> None:
    """After a receipt posts: any line still short of what is expected
    (ordered less cancelled) is a quantity discrepancy for the creator.
    Material and supplier always match by construction -- a receipt can
    only reference this PO's own lines."""
    short = [
        line for line in _lines(db, purchase_order) if line.received_quantity < line.quantity - line.cancelled_quantity
    ]
    if short:
        details = "; ".join(
            f"{material_names.get(line.raw_material_id, f'#{line.raw_material_id}')}: ordered "
            f"{_fmt(line.quantity - line.cancelled_quantity)}, received {_fmt(line.received_quantity)}"
            for line in short
        )
        _open(db, purchase_order, RECONCILIATION_RECEIPT, f"Quantity short -- {details}.")


def check_payment_discrepancy(db: Session, purchase_order: PurchaseOrder, *, final_payment: bool) -> None:
    """Paid more than the final amount, or a payment marked final that
    doesn't settle it exactly: returned to the creator instead of closing."""
    final = final_amount(purchase_order, _lines(db, purchase_order))
    paid = _paid(db, purchase_order)
    if paid > final or (final_payment and paid != final):
        _open(
            db,
            purchase_order,
            RECONCILIATION_PAYMENT,
            f"Paid {_fmt(paid)} {purchase_order.currency} against a PO amount of {_fmt(final)} "
            f"{purchase_order.currency} (difference {_fmt(paid - final)}).",
        )


def refresh_status(db: Session, purchase_order: PurchaseOrder) -> None:
    """Derives the status of an approved PO (docs/modules/purchase_orders.md
    Revision 6). A PO closes only when everything expected has been
    received, no discrepancy is open, and the amount paid equals the final
    amount."""
    if purchase_order.status not in FULFILMENT_STATUSES or purchase_order.status == CLOSED:
        return
    open_kinds = {rec.kind for rec in _open_reconciliations(db, purchase_order)}
    lines = _lines(db, purchase_order)
    any_received = any(line.received_quantity > 0 for line in lines)
    all_received = bool(lines) and all(line.received_quantity >= line.quantity - line.cancelled_quantity for line in lines)

    if RECONCILIATION_RECEIPT in open_kinds:
        status = RECONCILIATION_REQUIRED
    elif RECONCILIATION_PAYMENT in open_kinds:
        status = PAYMENT_RECONCILIATION
    elif all_received and any_received:
        status = CLOSED if _paid(db, purchase_order) == final_amount(purchase_order, lines) else RECEIVED
    elif any_received:
        status = PARTIALLY_RECEIVED
    else:
        status = SENT if purchase_order.sent_at else APPROVED
    purchase_order.status = status
    db.add(purchase_order)
    db.flush()


def resolve_reconciliation(
    db: Session,
    *,
    purchase_order: PurchaseOrder,
    reconciliation: PurchaseOrderReconciliation,
    resolution: str,
    note: str,
    resolved_by_user_id: int | None,
) -> None:
    """The creator's documented decision on an open discrepancy."""
    if reconciliation.status != RECONCILIATION_OPEN:
        raise BusinessRuleError("This discrepancy has already been resolved.")
    allowed = RECEIPT_RESOLUTIONS if reconciliation.kind == RECONCILIATION_RECEIPT else PAYMENT_RESOLUTIONS
    if resolution not in allowed:
        raise ValidationError(
            f"'{resolution}' is not a valid resolution for this discrepancy.",
            fields={"resolution": f"Must be one of {allowed}."},
        )

    lines = _lines(db, purchase_order)
    if resolution in (RESOLVE_CANCEL_REMAINING, RESOLVE_ACCEPT_RECEIVED_QUANTITY):
        if not any(line.received_quantity > 0 for line in lines):
            raise BusinessRuleError("Nothing has been received -- cancel the purchase order instead.")
        before = final_amount(purchase_order, lines)
        for line in lines:
            line.cancelled_quantity = max(line.quantity - line.received_quantity, Decimal("0"))
            db.add(line)
        db.flush()
        if resolution == RESOLVE_ACCEPT_RECEIVED_QUANTITY:
            # Operationally accepted, never financially: the amount owed
            # stays exactly what it was before the outstanding quantity
            # was cancelled.
            purchase_order.amount_adjustment += before - final_amount(purchase_order, lines)
            db.add(purchase_order)
    elif resolution == RESOLVE_ACCEPT_PAID_AMOUNT:
        purchase_order.amount_adjustment += _paid(db, purchase_order) - final_amount(purchase_order, lines)
        db.add(purchase_order)

    reconciliation.status = RECONCILIATION_RESOLVED
    reconciliation.resolution = resolution
    reconciliation.resolution_note = note
    reconciliation.resolved_at = datetime.utcnow()
    reconciliation.resolved_by_user_id = resolved_by_user_id
    db.add(reconciliation)
    db.flush()

    if resolution == RESOLVE_CANCEL_REMAINING:
        # A smaller final amount can leave the PO overpaid.
        check_payment_discrepancy(db, purchase_order, final_payment=False)
    refresh_status(db, purchase_order)


def submit_for_approval(db: Session, *, purchase_order: PurchaseOrder) -> None:
    """`draft -> pending_approval`. Every required field must be present:
    at least one item, expected delivery date, payment terms, currency
    (docs/modules/purchase_orders.md #2)."""
    assert_transition_allowed(purchase_order.status, PENDING_APPROVAL)
    has_line = db.query(PurchaseOrderLine.id).filter(PurchaseOrderLine.purchase_order_id == purchase_order.id).first()
    missing = [
        label
        for label, value in (
            ("at least one item", has_line),
            ("expected delivery date", purchase_order.expected_delivery_date),
            ("payment terms", (purchase_order.payment_terms or "").strip()),
            ("currency", purchase_order.currency),
        )
        if not value
    ]
    if missing:
        raise BusinessRuleError(f"Cannot submit for approval -- missing {', '.join(missing)}.")
    purchase_order.status = PENDING_APPROVAL
    db.add(purchase_order)


def approve_purchase_order(db: Session, *, purchase_order: PurchaseOrder, approved_by_user_id: int | None) -> PurchaseOrderRevision:
    """`pending_approval -> approved` (docs/modules/purchase_orders.md
    #23/#24): snapshots the PO's current header/lines into a new,
    immutable PurchaseOrderRevision -- the document that gets sent."""
    assert_transition_allowed(purchase_order.status, APPROVED)
    lines = db.query(PurchaseOrderLine).filter(PurchaseOrderLine.purchase_order_id == purchase_order.id).all()
    if not lines:
        raise BusinessRuleError("Cannot approve a purchase order with no items.")

    now = datetime.utcnow()
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
        issued_at=now,
        issued_by_user_id=approved_by_user_id,
    )
    db.add(revision)
    db.flush()

    for line in lines:
        db.add(
            PurchaseOrderRevisionLine(
                revision_id=revision.id,
                raw_material_id=line.raw_material_id,
                quantity=line.quantity,
                unit_of_measure_id=line.unit_of_measure_id,
                unit_price=line.unit_price,
                line_total=line.line_total,
                required_by_date=line.required_by_date,
                remarks=line.remarks,
            )
        )

    purchase_order.status = APPROVED
    purchase_order.revision_number = next_revision_number
    purchase_order.approved_at = now
    purchase_order.approved_by_user_id = approved_by_user_id
    db.add(purchase_order)
    db.flush()
    return revision


def mark_sent(purchase_order: PurchaseOrder, *, sent_by_user_id: int | None) -> None:
    """`approved -> sent` -- by email or by hand (WhatsApp, delivered)."""
    assert_transition_allowed(purchase_order.status, SENT)
    purchase_order.status = SENT
    purchase_order.sent_at = datetime.utcnow()
    purchase_order.sent_by_user_id = sent_by_user_id


def payment_status(total: Decimal, paid: Decimal) -> str:
    if paid <= 0:
        return UNPAID
    return PAID if paid >= total else PARTIALLY_PAID


def generate_receipt_number(db: Session, organisation_id: int, today: date | None = None) -> str:
    """`YY9NNNN` -- the fourth use of the same generator shape (RFQ `3`,
    PO `5`, Payment `7`), for Goods Receipt (docs/modules/purchase_orders.md
    #40)."""
    return document_numbering.next_yearly_number(
        db,
        number_column=PurchaseOrderReceipt.receipt_number,
        organisation_column=PurchaseOrderReceipt.organisation_id,
        organisation_id=organisation_id,
        type_digit=document_numbering.GOODS_RECEIPT_TYPE_DIGIT,
        today=today or date.today(),
        limit_message="This organisation has reached the maximum number of goods receipts for this year.",
    )


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
    remarks: dict[int, str | None] | None = None,
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
        raise BusinessRuleError("Goods can only be received against a purchase order that has been sent.")
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
        remaining = line.quantity - line.cancelled_quantity - line.received_quantity
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
        try:
            # A SAVEPOINT, not db.rollback(): a number collision undoes only
            # this insert, never other work already flushed in the same
            # transaction (same pattern as inventory_service._increment_inventory).
            with savepoint(db):
                db.add(receipt)
                db.flush()
            last_error = None
            break
        except IntegrityError as exc:
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
                remarks=(remarks or {}).get(line.id),
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
    factors = _conversion_factors(db, receipt_lines)
    stock_units = _stock_units(db, receipt_lines)
    for receipt_line in receipt_lines:
        po_line_rowcount = (
            db.query(PurchaseOrderLine)
            .filter(
                PurchaseOrderLine.id == receipt_line.purchase_order_line_id,
                PurchaseOrderLine.received_quantity + receipt_line.quantity
                <= PurchaseOrderLine.quantity - PurchaseOrderLine.cancelled_quantity,
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
            quantity=_stock_quantity(receipt_line.quantity, factors[receipt_line.purchase_order_line_id]),
            unit_of_measure_id=stock_units[receipt_line.raw_material_id],
            reference_type=PURCHASE_ORDER_RECEIPT_LINE_REFERENCE,
            reference_id=receipt_line.id,
            created_by_user_id=posted_by_user_id,
        )

    db.flush()
    material_names = dict(
        db.query(RawMaterial.id, RawMaterial.name)
        .filter(RawMaterial.id.in_({line.raw_material_id for line in receipt_lines}))
        .all()
    )
    check_receipt_discrepancy(db, purchase_order, material_names)
    refresh_status(db, purchase_order)


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
    factors = _conversion_factors(db, receipt_lines)

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
            quantity=_stock_quantity(receipt_line.quantity, factors[receipt_line.purchase_order_line_id]),
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
    refresh_status(db, purchase_order)


def _conversion_factors(db: Session, receipt_lines: list[PurchaseOrderReceiptLine]) -> dict[int, Decimal]:
    ids = {line.purchase_order_line_id for line in receipt_lines}
    return dict(
        db.query(PurchaseOrderLine.id, PurchaseOrderLine.conversion_factor).filter(PurchaseOrderLine.id.in_(ids)).all()
    )


def _stock_units(db: Session, receipt_lines: list[PurchaseOrderReceiptLine]) -> dict[int, int]:
    """Each receipt line's raw material's own current stock unit --
    inventory quantities are always kept in this unit (never re-derived
    later: a material's unit is permanently frozen the instant any
    StockMovement exists for it, app/api/raw_materials.py's
    _has_recorded_quantity). Resolved once per post/reverse call and
    passed straight through to inventory_service, which never re-resolves
    it itself (gap-fix: Inventory ledger hardening -- movement UOM)."""
    ids = {line.raw_material_id for line in receipt_lines}
    return dict(db.query(RawMaterial.id, RawMaterial.unit_of_measure_id).filter(RawMaterial.id.in_(ids)).all())


def _stock_quantity(quantity: Decimal, factor: Decimal) -> Decimal:
    """Receipts are in the PO line's purchase unit; stock is always kept
    in the material's own unit."""
    return quantity if factor == 1 else (quantity * factor).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def generate_payment_number(db: Session, organisation_id: int, today: date | None = None) -> str:
    """`YY7NNNN` -- the same generator shape used twice already
    (RFQ's `3`, Purchase Order's `5`), extended with a third fixed digit
    (`7`) for this document type (docs/modules/purchase_orders.md #31)."""
    return document_numbering.next_yearly_number(
        db,
        number_column=PurchaseOrderPayment.payment_number,
        organisation_column=PurchaseOrderPayment.organisation_id,
        organisation_id=organisation_id,
        type_digit=document_numbering.PURCHASE_ORDER_PAYMENT_TYPE_DIGIT,
        today=today or date.today(),
        limit_message="This organisation has reached the maximum number of payments for this year.",
    )


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
    is_final: bool = False,
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
        raise BusinessRuleError("Payments can only be recorded against an approved, open purchase order.")
    if amount <= 0:
        raise ValidationError("Payment amount must be greater than zero.")
    # A payment that doesn't match is still recorded -- Finance records
    # what was actually paid; the difference goes to the PO creator
    # (check_payment_discrepancy, called by the API after this).

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
            is_final=is_final,
            created_by_user_id=created_by_user_id,
        )
        try:
            # A SAVEPOINT, not db.rollback(): a number collision undoes only
            # this insert, never other work already flushed in the same
            # transaction (same pattern as inventory_service._increment_inventory).
            with savepoint(db):
                db.add(payment)
                db.flush()
            return payment
        except IntegrityError as exc:
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
