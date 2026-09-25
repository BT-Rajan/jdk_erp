from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import OrganisationScopedMixin, TimestampMixin

DRAFT = "draft"
PENDING_APPROVAL = "pending_approval"
APPROVED = "approved"
SENT = "sent"
PARTIALLY_RECEIVED = "partially_received"
RECONCILIATION_REQUIRED = "reconciliation_required"
RECEIVED = "received"
PAYMENT_RECONCILIATION = "payment_reconciliation"
CLOSED = "closed"
CANCELLED = "cancelled"
PURCHASE_ORDER_STATUSES = (
    DRAFT,
    PENDING_APPROVAL,
    APPROVED,
    SENT,
    PARTIALLY_RECEIVED,
    RECONCILIATION_REQUIRED,
    RECEIVED,
    PAYMENT_RECONCILIATION,
    CLOSED,
    CANCELLED,
)
# Statuses after approval that app/services/purchase_order_service.
# refresh_status derives from receipts, payments and open reconciliations
# -- never direct targets of a status change.
FULFILMENT_STATUSES = (
    APPROVED,
    SENT,
    PARTIALLY_RECEIVED,
    RECONCILIATION_REQUIRED,
    RECEIVED,
    PAYMENT_RECONCILIATION,
    CLOSED,
)

# docs/modules/purchase_orders.md Revision 6.
# draft -> pending_approval (submit) -> approved (approve: snapshots the
# revision + PDF) -> sent (emailed or marked sent). From there the status
# is derived (refresh_status): partially_received, reconciliation_required
# (a receipt short of the order, until the creator resolves it), received
# (awaiting payment), payment_reconciliation (paid != final amount, until
# the creator resolves it) and closed (fully received, nothing open, paid
# == final amount). pending_approval -> draft is "send back";
# approved/sent -> draft is "Create Revision" and needs approval again.
ALLOWED_STATUS_TRANSITIONS = {
    DRAFT: {PENDING_APPROVAL, CANCELLED},
    PENDING_APPROVAL: {APPROVED, DRAFT, CANCELLED},
    APPROVED: {SENT, DRAFT, CANCELLED},
    SENT: {DRAFT, CANCELLED},
    PARTIALLY_RECEIVED: {CANCELLED},
    RECONCILIATION_REQUIRED: set(),
    RECEIVED: set(),
    PAYMENT_RECONCILIATION: set(),
    CLOSED: set(),
    CANCELLED: set(),
}

DEFAULT_CURRENCY = "KWD"


class PurchaseOrder(Base, TimestampMixin, OrganisationScopedMixin):
    """The business decision to purchase specified raw materials from a
    supplier, and — once issued — a controlled commercial document with
    an immutable revision history (docs/modules/purchase_orders.md,
    Revision 2) -- audited against jdk_clean first
    (docs/audit/PROCUREMENT_AUDIT.md), which has a real, working
    implementation this module reuses far more than it invents.

    `supplier_id`/`warehouse_id` are immutable after creation -- sever and
    create a new PO instead of repointing one, the same discipline
    `Bom.product_id` already established. `warehouse_id` has no jdk_clean
    precedent at all (that codebase has no warehouse/location concept
    anywhere); jdk_erp already has a real Warehouse master, so every PO
    commits to exactly one destination warehouse for all of its lines,
    never a per-line or per-receipt warehouse choice.

    `rfq_id` records which RFQ (if any) this PO was converted from
    (docs/modules/rfq.md #8) -- nullable, since a PO may still be created
    directly with no RFQ.

    `revision_number` starts at 0 (never issued) and increments by one on
    every approval, each one snapshotted into its own
    immutable `PurchaseOrderRevision` row (#24) -- the PO's own header/
    lines here always reflect the *current* (possibly still-being-
    negotiated) state, never a specific historical revision.

    `currency` is the PO's own (default KWD). Approval/send/cancel
    stamps record who did each step and when; `created_by_user_id` who
    raised it.

    No commercial total fields stored here -- `total_amount` is always
    the sum of line totals, computed at read time (app/services/
    purchase_order_service.total_amount), never a second stored value
    that could drift from the lines it's derived from. No PO-level
    discount/tax field either -- no evidenced JDK need
    (docs/audit/PROCUREMENT_AUDIT.md Revision 2 #8)."""

    __tablename__ = "purchase_orders"
    __table_args__ = (
        UniqueConstraint("organisation_id", "po_number", name="uq_purchase_orders_organisation_id_po_number"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    po_number: Mapped[str] = mapped_column(String(20), nullable=False)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False, index=True)
    warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    # use_alter=True: purchase_orders.rfq_id and rfqs.purchase_order_id
    # form a second circular FK pair (mirroring rfqs.selected_response_id
    # above) -- deferred to an ALTER TABLE after both tables exist.
    rfq_id: Mapped[int | None] = mapped_column(
        ForeignKey("rfqs.id", ondelete="SET NULL", use_alter=True, name="fk_purchase_orders_rfq_id_rfqs"),
        nullable=True,
        index=True,
    )
    # The supplier quotation this PO was generated from (RFQ -> Supplier
    # Quotation -> PO traceability). Reference only: the PO's own lines
    # hold the final agreed quantities/prices. use_alter: part of the
    # rfqs <-> purchase_orders FK cycle.
    rfq_response_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "rfq_responses.id", ondelete="SET NULL", use_alter=True, name="fk_purchase_orders_rfq_response_id_rfq_responses"
        ),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, default=DRAFT, server_default=DRAFT)
    revision_number: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    # Set only by resolving a payment reconciliation with "accept paid
    # amount": final amount = received-value total + this adjustment.
    amount_adjustment: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False, default=0, server_default="0")
    order_date: Mapped[date] = mapped_column(Date, nullable=False)
    expected_delivery_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    supplier_reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    payment_terms: Mapped[str | None] = mapped_column(String(200), nullable=True)
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default=DEFAULT_CURRENCY, server_default=DEFAULT_CURRENCY
    )
    delivery_instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Approval & history (docs/modules/purchase_orders.md #23). The full
    # change log is the audit trail (audit_events).
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    approved_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    sent_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cancelled_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    # Retired "supplier confirmed" step -- kept only for historical rows.
    supplier_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    supplier_confirmed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    supplier_confirmation_note: Mapped[str | None] = mapped_column(Text, nullable=True)


class PurchaseOrderLine(Base, TimestampMixin):
    """One Raw Material on a Purchase Order, in its purchase unit
    (`unit_of_measure_id`, defaulting to the material's own unit).
    `conversion_factor` is `1 purchase unit = factor material units`,
    fixed when the line is written, and used only when a receipt posts
    stock in the material's own unit (docs/modules/purchase_orders.md #5). No `organisation_id` of its own
    -- a child of an already organisation-scoped `PurchaseOrder`, the same
    shape `BomComponent` already uses. Always the PO's *current* line
    state -- what the next revision would snapshot if issued
    (docs/modules/purchase_orders.md #24).

    `unit_price`/`line_total` are snapshots at order time, never read
    live from RawMaterial afterward (docs/audit/RAW_MATERIALS_AUDIT.md
    #7's binding rule for whenever this module was built).
    `received_quantity` is a cumulative receiving-progress counter, only
    ever written by app/services/purchase_order_service.receive_lines's
    atomic conditional UPDATE (docs/modules/purchase_orders.md #8) -- it
    is never itself the authoritative stock quantity; that's
    RawMaterialInventory.quantity_on_hand (app/models/inventory.py)."""

    __tablename__ = "purchase_order_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    purchase_order_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    raw_material_id: Mapped[int] = mapped_column(
        ForeignKey("raw_materials.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    # Which RFQ line this PO line was converted from, when it was --
    # null for a PO raised directly with no RFQ. Lets several POs (one
    # per supplier) each source part of the same RFQ line's requirement
    # be added back up against it, to show how much has been sourced and
    # how much remains (gap-fix: split sourcing, docs/modules/rfq.md).
    rfq_line_id: Mapped[int | None] = mapped_column(
        ForeignKey("rfq_lines.id", ondelete="SET NULL"), nullable=True, index=True
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    unit_of_measure_id: Mapped[int] = mapped_column(
        ForeignKey("units_of_measure.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    conversion_factor: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=1, server_default="1")
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    required_by_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)
    received_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False, default=0, server_default="0")
    # Remaining quantity the creator cancelled when resolving a short
    # receipt ("accept received quantity"); no longer expected or payable.
    cancelled_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False, default=0, server_default="0")


class PurchaseOrderRevision(Base):
    """One immutable snapshot per `draft -> issued` transition
    (docs/modules/purchase_orders.md #24) -- the historical record of
    exactly what commercial terms were issued at that moment, never
    updated afterward and never regenerated from today's
    PurchaseOrderLine data. The PO's own `revision_number` always equals
    the highest `revision_number` snapshotted here."""

    __tablename__ = "purchase_order_revisions"
    __table_args__ = (
        UniqueConstraint(
            "purchase_order_id", "revision_number", name="uq_purchase_order_revisions_purchase_order_id_revision_number"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    purchase_order_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    revision_number: Mapped[int] = mapped_column(nullable=False)
    order_date: Mapped[date] = mapped_column(Date, nullable=False)
    expected_delivery_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    supplier_reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    payment_terms: Mapped[str | None] = mapped_column(String(200), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    issued_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class PurchaseOrderRevisionLine(Base):
    """A frozen copy of one PurchaseOrderLine as it existed at the moment
    its revision was issued (docs/modules/purchase_orders.md #24) -- never
    a live reference to the current (possibly since-edited)
    `purchase_order_lines` row."""

    __tablename__ = "purchase_order_revision_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    revision_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_order_revisions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    raw_material_id: Mapped[int] = mapped_column(
        ForeignKey("raw_materials.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    unit_of_measure_id: Mapped[int | None] = mapped_column(
        ForeignKey("units_of_measure.id", ondelete="RESTRICT"), nullable=True
    )
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    required_by_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)


PAYMENT_RECORDED = "recorded"
PAYMENT_CANCELLED = "cancelled"
PURCHASE_ORDER_PAYMENT_STATUSES = (PAYMENT_RECORDED, PAYMENT_CANCELLED)


class PurchaseOrderPayment(Base, TimestampMixin, OrganisationScopedMixin):
    """Money actually paid to a supplier against one PO
    (docs/modules/purchase_orders.md #30, Revision 3) -- audited against
    both codebases first (docs/audit/PROCUREMENT_AUDIT.md Revision 3):
    jdk_clean's own `Payment` model is customer-side (accounts
    receivable, `order_id`/`customer_id`), not supplier-side, so this is
    a new model adapting its useful *shape* (free-text `payment_method`/
    `reference_number`, no fixed enum) rather than reusing it directly.

    `status` (`recorded`/`cancelled`), not a soft delete -- the task's
    own requirement is that a cancelled payment stays fully visible in
    history with its original amount intact, never filtered out of view
    the way `SoftDeleteMixin` would. `purchase_order_id` is immutable;
    there is no "edit a payment" endpoint -- cancel and record a fresh
    one, the same "never silently rewrite a financial entry" discipline
    `purchase_order_lines`/`stock_movements` already apply to their own
    historical rows."""

    __tablename__ = "purchase_order_payments"
    __table_args__ = (
        UniqueConstraint(
            "organisation_id", "payment_number", name="uq_purchase_order_payments_organisation_id_payment_number"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    payment_number: Mapped[str] = mapped_column(String(20), nullable=False)
    purchase_order_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_orders.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    payment_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    payment_method: Mapped[str | None] = mapped_column(String(60), nullable=True)
    reference_number: Mapped[str | None] = mapped_column(String(120), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Finance marks the payment that settles the PO; if the total paid
    # then differs from the final amount, the PO goes to payment
    # reconciliation instead of closing.
    is_final: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    status: Mapped[str] = mapped_column(String(10), nullable=False, default=PAYMENT_RECORDED, server_default=PAYMENT_RECORDED)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cancelled_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


RECEIPT_DRAFT = "draft"
RECEIPT_POSTED = "posted"
RECEIPT_CANCELLED = "cancelled"
RECEIPT_REVERSED = "reversed"
PURCHASE_ORDER_RECEIPT_STATUSES = (RECEIPT_DRAFT, RECEIPT_POSTED, RECEIPT_CANCELLED, RECEIPT_REVERSED)

# docs/modules/purchase_orders.md #38 -- draft is the only editable
# state; posted is the one-way transition that creates the inventory
# effect (never a direct-PATCH-reachable status, only
# purchase_order_service.post_receipt's own action); reversed and
# cancelled are both terminal.
ALLOWED_RECEIPT_STATUS_TRANSITIONS = {
    RECEIPT_DRAFT: {RECEIPT_POSTED, RECEIPT_CANCELLED},
    RECEIPT_POSTED: {RECEIPT_REVERSED},
    RECEIPT_CANCELLED: set(),
    RECEIPT_REVERSED: set(),
}


class PurchaseOrderReceipt(Base, TimestampMixin, OrganisationScopedMixin):
    """What physically arrived against one Purchase Order
    (docs/modules/purchase_orders.md #37, Revision 4) -- audited against
    both codebases first (docs/audit/PROCUREMENT_AUDIT.md Revision 4):
    neither jdk_clean nor this codebase's own first version had a
    separate goods-receipt entity (receiving was a plain action against
    PO lines) -- this is a genuine, explicit supersession of that
    decision, not a refactor of existing prior art.

    `warehouse_id` is copied from the PO at creation time and never
    re-chosen -- a PO already commits to exactly one destination
    warehouse for all of its lines (`PurchaseOrder.warehouse_id`'s own
    docstring), so its receipts do too (Revision 4 audit #10).

    `status` is the idempotency guard for posting (Revision 4 audit #7):
    `draft -> posted` is only ever reachable once, enforced by an atomic
    conditional UPDATE in app/services/purchase_order_service.post_receipt,
    not a second dedup field. A posted receipt is never edited -- correct
    it by reversing (`posted -> reversed`, `reversal_reason` required) and
    creating a fresh receipt, the same "cancel/reverse and record a fresh
    one, never edit" discipline PurchaseOrderPayment already established."""

    __tablename__ = "purchase_order_receipts"
    __table_args__ = (
        UniqueConstraint(
            "organisation_id", "receipt_number", name="uq_purchase_order_receipts_organisation_id_receipt_number"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    receipt_number: Mapped[str] = mapped_column(String(20), nullable=False)
    purchase_order_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    receipt_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default=RECEIPT_DRAFT, server_default=RECEIPT_DRAFT)
    supplier_delivery_reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    posted_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cancelled_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reversed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reversal_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class PurchaseOrderReceiptLine(Base):
    """One Purchase Order line's physical arrival on one receipt
    (docs/modules/purchase_orders.md #37) -- always points at an existing
    `purchase_order_line_id` (never an arbitrary/unordered material, the
    task's own explicit rule) and snapshots `raw_material_id`, the same
    "freeze the fact" discipline `PurchaseOrderRevisionLine` already uses.
    `quantity` is in that PO line's own already-fixed unit -- no
    receipt-line UOM field exists, so no unit mismatch is representable
    here (docs/audit/PROCUREMENT_AUDIT.md Revision 4 #4)."""

    __tablename__ = "purchase_order_receipt_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    receipt_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_order_receipts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    purchase_order_line_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_order_lines.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    raw_material_id: Mapped[int] = mapped_column(
        ForeignKey("raw_materials.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)


RECONCILIATION_RECEIPT = "receipt"
RECONCILIATION_PAYMENT = "payment"
RECONCILIATION_OPEN = "open"
RECONCILIATION_RESOLVED = "resolved"

# Resolutions the PO creator can choose (docs/modules/purchase_orders.md
# Revision 6).
RESOLVE_KEEP_PENDING = "keep_pending"  # remaining stays expected (incl. replacement requested)
# Accept what was received as final for this line -- the outstanding
# quantity is cancelled (the only way to stop a line blocking
# all_received without rewriting its original ordered quantity), but
# the PO's final_amount is held unchanged via amount_adjustment: the
# short quantity is accepted operationally, never financially. Distinct
# from RESOLVE_CANCEL_REMAINING, which lowers what's owed.
RESOLVE_ACCEPT_RECEIVED_QUANTITY = "accept_received_quantity"
RESOLVE_CANCEL_REMAINING = "cancel_remaining"  # accept what was received; the rest is cancelled, final_amount reduced
RESOLVE_ACCEPT_PAID_AMOUNT = "accept_paid_amount"  # final amount becomes what was paid
RESOLVE_CORRECT_PAYMENT = "correct_payment"  # Finance corrects the payment(s)
RECEIPT_RESOLUTIONS = (RESOLVE_KEEP_PENDING, RESOLVE_ACCEPT_RECEIVED_QUANTITY, RESOLVE_CANCEL_REMAINING)
PAYMENT_RESOLUTIONS = (RESOLVE_ACCEPT_PAID_AMOUNT, RESOLVE_CORRECT_PAYMENT)


class PurchaseOrderReconciliation(Base, TimestampMixin):
    """A discrepancy returned to the PO creator: a receipt short of the
    order (`receipt`) or a paid total different from the final amount
    (`payment`). While one is open the PO can't close. Resolved only by
    the creator (or an admin), always with a documented note."""

    __tablename__ = "purchase_order_reconciliations"

    id: Mapped[int] = mapped_column(primary_key=True)
    purchase_order_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default=RECONCILIATION_OPEN, server_default=RECONCILIATION_OPEN)
    discrepancy: Mapped[str] = mapped_column(Text, nullable=False)
    resolution: Mapped[str | None] = mapped_column(String(30), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resolved_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


COMMUNICATION_PO_SENT = "po_sent"
COMMUNICATION_FOLLOW_UP = "follow_up"
COMMUNICATION_NOTE = "note"
COMMUNICATION_SENT = "sent"
COMMUNICATION_FAILED = "failed"
COMMUNICATION_RECORDED = "recorded"


class PurchaseOrderCommunication(Base, TimestampMixin):
    """One entry in a PO's supplier follow-up history: the PO being sent,
    a follow-up email, or a recorded supplier reply ("confirmed delivery
    for 30-09"). Attachments are generic files
    (`entity_type="purchase_order_communication"`)."""

    __tablename__ = "purchase_order_communications"

    id: Mapped[int] = mapped_column(primary_key=True)
    purchase_order_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    recipient: Mapped[str | None] = mapped_column(String(255), nullable=True)
    subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(10), nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
