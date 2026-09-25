from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.payment_terms import normalise_payment_terms
from app.models.purchase_order import CANCELLED, DRAFT
from app.schemas.file import FileOut


def _strip_or_none(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


class PurchaseOrderLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    raw_material_id: int
    quantity: Decimal
    unit_of_measure_id: int
    conversion_factor: Decimal
    unit_price: Decimal
    line_total: Decimal
    required_by_date: date | None
    remarks: str | None
    received_quantity: Decimal
    cancelled_quantity: Decimal


class PurchaseOrderRevisionLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    raw_material_id: int
    quantity: Decimal
    unit_of_measure_id: int | None
    unit_price: Decimal
    line_total: Decimal
    required_by_date: date | None
    remarks: str | None


class PurchaseOrderRevisionOut(BaseModel):
    """A revision is an immutable snapshot (docs/modules/purchase_orders.md
    #24) -- this schema is read-only, there is no matching *Request type
    a caller can PATCH."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    revision_number: int
    order_date: date
    expected_delivery_date: date | None
    supplier_reference: str | None
    payment_terms: str | None
    notes: str | None
    total_amount: Decimal
    issued_at: datetime
    issued_by_user_id: int | None
    lines: list[PurchaseOrderRevisionLineOut]
    pdf_file: FileOut | None = None


class PurchaseOrderPaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    payment_number: str
    payment_date: date
    amount: Decimal
    payment_method: str | None
    reference_number: str | None
    notes: str | None
    is_final: bool
    status: str
    cancelled_at: datetime | None
    cancelled_by_user_id: int | None
    cancellation_reason: str | None
    created_by_user_id: int | None
    created_at: datetime
    files: list[FileOut] = []


class PurchaseOrderReceiptLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    purchase_order_line_id: int
    raw_material_id: int
    quantity: Decimal
    remarks: str | None = None


class PurchaseOrderReceiptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    receipt_number: str
    purchase_order_id: int
    warehouse_id: int
    receipt_date: date
    status: str
    supplier_delivery_reference: str | None
    notes: str | None
    posted_at: datetime | None
    posted_by_user_id: int | None
    cancelled_at: datetime | None
    cancelled_by_user_id: int | None
    reversed_at: datetime | None
    reversed_by_user_id: int | None
    reversal_reason: str | None
    created_by_user_id: int | None
    created_at: datetime
    received_by_name: str | None = None
    # Receipt date after the PO's expected delivery date -- shown, never
    # blocking.
    days_late: int = 0
    lines: list[PurchaseOrderReceiptLineOut] = []
    documents: list[FileOut] = []


class PurchaseOrderReconciliationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    status: str
    discrepancy: str
    resolution: str | None
    resolution_note: str | None
    created_at: datetime
    resolved_at: datetime | None
    resolved_by_user_id: int | None
    resolved_by_name: str | None = None


class PurchaseOrderCommunicationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    recipient: str | None
    subject: str | None
    message: str | None
    status: str
    error: str | None
    created_at: datetime
    sent_by_user_id: int | None
    sent_by_name: str | None = None
    files: list[FileOut] = []


class PurchaseOrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organisation_id: int
    po_number: str
    supplier_id: int
    warehouse_id: int
    rfq_id: int | None
    rfq_number: str | None = None
    rfq_response_id: int | None
    status: str
    revision_number: int
    order_date: date
    expected_delivery_date: date | None
    supplier_reference: str | None
    payment_terms: str | None
    currency: str
    delivery_instructions: str | None
    notes: str | None
    cancel_reason: str | None
    created_at: datetime
    created_by_user_id: int | None
    approved_at: datetime | None
    approved_by_user_id: int | None
    sent_at: datetime | None
    sent_by_user_id: int | None
    cancelled_at: datetime | None
    cancelled_by_user_id: int | None
    created_by_name: str | None = None
    approved_by_name: str | None = None
    sent_by_name: str | None = None
    cancelled_by_name: str | None = None
    total_amount: Decimal
    amount_adjustment: Decimal
    final_amount: Decimal
    paid_amount: Decimal
    outstanding_amount: Decimal
    # What's already been paid toward a now-cancelled order -- 0 unless
    # `status` is `cancelled` and a payment was recorded. Never an actual
    # refund transaction, just the figure that one is owed (gap-fix:
    # supplier-failure cancellation, docs/modules/purchase_orders.md).
    refundable_amount: Decimal = Decimal("0.0000")
    payment_status: str
    lines: list[PurchaseOrderLineOut]
    revisions: list[PurchaseOrderRevisionOut]
    documents: list[FileOut]
    payments: list[PurchaseOrderPaymentOut]
    receipts: list[PurchaseOrderReceiptOut]
    reconciliations: list[PurchaseOrderReconciliationOut] = []
    communications: list[PurchaseOrderCommunicationOut] = []


class PurchaseOrderCreateRequest(BaseModel):
    """PO header (docs/modules/purchase_orders.md #2). `po_number` and
    `order_date` (today) are server-stamped. Items are added afterward
    via POST .../lines; at least one is required to submit for approval.
    `rfq_id` is only ever set by the RFQ's PO-generation step."""

    supplier_id: int
    expected_delivery_date: date
    payment_terms: str = Field(min_length=1, max_length=200)
    supplier_reference: str | None = Field(default=None, max_length=100)
    delivery_instructions: str | None = Field(default=None, max_length=2000)
    notes: str | None = Field(default=None, max_length=4000)

    @field_validator("payment_terms")
    @classmethod
    def _check_payment_terms(cls, value: str) -> str:
        return normalise_payment_terms(value)

    @field_validator("supplier_reference", "delivery_instructions", "notes")
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        return _strip_or_none(value)


class PurchaseOrderUpdateRequest(BaseModel):
    """Draft-only (enforced in app/api/purchase_orders.py).
    `supplier_id`/`rfq_id` are immutable."""

    expected_delivery_date: date | None = None
    payment_terms: str | None = Field(default=None, max_length=200)
    supplier_reference: str | None = Field(default=None, max_length=100)
    delivery_instructions: str | None = Field(default=None, max_length=2000)
    notes: str | None = Field(default=None, max_length=4000)

    @field_validator("expected_delivery_date", "payment_terms")
    @classmethod
    def _not_null(cls, value, info):
        if value is None or (isinstance(value, str) and not value.strip()):
            raise ValueError(f"{info.field_name} is required.")
        if info.field_name == "payment_terms":
            return normalise_payment_terms(value)
        return value

    @field_validator("supplier_reference", "delivery_instructions", "notes")
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        return _strip_or_none(value)


class PurchaseOrderLineCreateRequest(BaseModel):
    """`unit_of_measure_id` omitted -> the material's own unit; otherwise
    it must convert to that unit (app/services/uom_conversion.py)."""

    raw_material_id: int
    quantity: Decimal = Field(max_digits=14, decimal_places=4)
    unit_price: Decimal = Field(max_digits=14, decimal_places=4)
    unit_of_measure_id: int | None = None
    required_by_date: date | None = None
    remarks: str | None = Field(default=None, max_length=2000)

    @field_validator("quantity")
    @classmethod
    def _check_positive_quantity(cls, value: Decimal) -> Decimal:
        if value <= 0:
            raise ValueError("Quantity must be greater than zero.")
        return value

    @field_validator("unit_price")
    @classmethod
    def _check_positive_price(cls, value: Decimal) -> Decimal:
        if value <= 0:
            raise ValueError("Unit price must be greater than zero.")
        return value

    @field_validator("remarks")
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        return _strip_or_none(value)


class PurchaseOrderLineUpdateRequest(BaseModel):
    """`raw_material_id` is immutable -- remove and re-add the line
    instead of repointing it to a different material."""

    quantity: Decimal | None = Field(default=None, max_digits=14, decimal_places=4)
    unit_price: Decimal | None = Field(default=None, max_digits=14, decimal_places=4)
    unit_of_measure_id: int | None = None
    required_by_date: date | None = None
    remarks: str | None = Field(default=None, max_length=2000)

    @field_validator("quantity", "unit_price", "unit_of_measure_id")
    @classmethod
    def _check_positive(cls, value, info):
        if value is None:
            raise ValueError(f"{info.field_name} cannot be null.")
        if value <= 0:
            raise ValueError(f"{info.field_name} must be greater than zero.")
        return value

    @field_validator("remarks")
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        return _strip_or_none(value)


class PurchaseOrderStatusChangeRequest(BaseModel):
    """`status` must be `draft` (send a pending PO back, or reopen an
    approved/sent PO as a new revision -- docs/modules/purchase_orders.md
    #23) or `cancelled` (reason required). Submit, approve and send are
    their own actions; received statuses are only ever side effects."""

    status: str
    cancel_reason: str | None = None

    @field_validator("status")
    @classmethod
    def _check_status(cls, value: str) -> str:
        if value not in (DRAFT, CANCELLED):
            raise ValueError(f"status must be one of {(DRAFT, CANCELLED)}.")
        return value

    @model_validator(mode="after")
    def _check_cancel_reason(self) -> "PurchaseOrderStatusChangeRequest":
        if self.status == CANCELLED:
            if not self.cancel_reason or not self.cancel_reason.strip():
                raise ValueError("cancel_reason is required when cancelling a purchase order.")
            self.cancel_reason = self.cancel_reason.strip()
        return self


class SendPurchaseOrderRequest(BaseModel):
    """`email=true` emails the approved PDF to the supplier; `false`
    records that it was sent another way (hand delivery, WhatsApp)."""

    email: bool = True


class CreateReceiptLineRequest(BaseModel):
    purchase_order_line_id: int
    quantity: Decimal
    remarks: str | None = Field(default=None, max_length=2000)

    @field_validator("remarks")
    @classmethod
    def _strip_remarks(cls, value: str | None) -> str | None:
        return _strip_or_none(value)

    @field_validator("quantity")
    @classmethod
    def _check_positive(cls, value: Decimal) -> Decimal:
        if value <= 0:
            raise ValueError("Quantity must be greater than zero.")
        return value


class CreateReceiptRequest(BaseModel):
    """docs/modules/purchase_orders.md #37/#39 -- starts the receipt as
    `draft`, zero inventory effect until POST .../post (#38)."""

    receipt_date: date
    supplier_delivery_reference: str | None = None
    notes: str | None = None
    lines: list[CreateReceiptLineRequest]
    file_ids: list[int] = []

    @field_validator("lines")
    @classmethod
    def _check_lines(cls, value: list[CreateReceiptLineRequest]) -> list[CreateReceiptLineRequest]:
        if not value:
            raise ValueError("At least one line must be received.")
        return value


class ReverseReceiptRequest(BaseModel):
    reason: str

    @field_validator("reason")
    @classmethod
    def _check_reason(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("A reason is required to reverse a goods receipt.")
        return value.strip()


class RecordPaymentRequest(BaseModel):
    """`is_final`: this payment settles the PO -- if the total paid then
    differs from the final amount, the PO goes to payment reconciliation."""

    payment_date: date
    amount: Decimal = Field(max_digits=14, decimal_places=4)
    payment_method: str | None = None
    reference_number: str | None = None
    notes: str | None = None
    is_final: bool = False
    file_ids: list[int] = []

    @field_validator("amount")
    @classmethod
    def _check_positive(cls, value: Decimal) -> Decimal:
        if value <= 0:
            raise ValueError("Amount must be greater than zero.")
        return value


class CancelPaymentRequest(BaseModel):
    reason: str

    @field_validator("reason")
    @classmethod
    def _check_reason(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("A reason is required to cancel a payment.")
        return value.strip()


class ResolveReconciliationRequest(BaseModel):
    """Receipt discrepancy: `keep_pending`, `accept_received_quantity`, or
    `cancel_remaining`. Payment discrepancy: `accept_paid_amount` or
    `correct_payment`. A documented note is always required."""

    resolution: str
    note: str = Field(min_length=1, max_length=4000)

    @field_validator("note")
    @classmethod
    def _check_note(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Document the resolution.")
        return value


class FollowUpRequest(BaseModel):
    """`send_email=true` emails the supplier (optionally attaching the
    current PO PDF and uploaded files); `false` records a supplier reply
    or phone call on the PO's history."""

    send_email: bool = True
    subject: str | None = Field(default=None, max_length=255)
    message: str = Field(min_length=1, max_length=8000)
    attach_po_pdf: bool = False
    file_ids: list[int] = Field(default_factory=list, max_length=5)

    @field_validator("subject")
    @classmethod
    def _strip_subject(cls, value: str | None) -> str | None:
        return _strip_or_none(value)

    @field_validator("message")
    @classmethod
    def _check_message(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("A message is required.")
        return value


# --- Goods receiving (warehouse) -- quantities only, never prices ------------


class ReceivingLineOut(BaseModel):
    id: int
    raw_material_id: int
    material_name: str
    unit_code: str
    ordered_quantity: Decimal
    received_quantity: Decimal
    remaining_quantity: Decimal


class ReceivingReceiptLineOut(BaseModel):
    material_name: str
    unit_code: str
    quantity: Decimal
    remarks: str | None


class ReceivingReceiptOut(BaseModel):
    id: int
    receipt_number: str
    receipt_date: date
    status: str
    posted_at: datetime | None
    received_by_name: str | None
    supplier_delivery_reference: str | None
    notes: str | None
    days_late: int
    lines: list[ReceivingReceiptLineOut]
    documents: list[FileOut]


class ReceivingOut(BaseModel):
    """What the warehouse needs to receive a PO -- deliberately no unit
    price, line value, total, payment or commercial terms. Enforced by
    this being the only shape the goods-receiving API returns."""

    id: int
    po_number: str
    supplier_name: str
    warehouse_name: str
    expected_delivery_date: date | None
    delivery_instructions: str | None
    status: str
    can_receive: bool
    lines: list[ReceivingLineOut]
    receipts: list[ReceivingReceiptOut]


# --- Finance (payments) -- the PO read-only, plus what's been paid -------------


class FinanceLineOut(BaseModel):
    material_name: str
    quantity: Decimal
    unit_code: str
    unit_price: Decimal
    line_total: Decimal


class FinancePaymentOut(BaseModel):
    id: int
    payment_number: str
    payment_date: date
    amount: Decimal
    payment_method: str | None
    notes: str | None
    status: str


class FinancePurchaseOrderOut(BaseModel):
    """What Finance sees of a PO (docs/modules/purchase_orders.md
    Revision 8): every field read-only; Finance only records payments
    against it."""

    id: int
    po_number: str
    supplier_name: str
    order_date: date
    expected_delivery_date: date | None
    payment_terms: str | None
    supplier_reference: str | None
    rfq_number: str | None
    notes: str | None
    status: str
    approved_at: datetime | None
    currency: str
    final_amount: Decimal
    paid_amount: Decimal
    outstanding_amount: Decimal
    # What's already been paid toward a now-cancelled order -- 0 unless
    # `status` is `cancelled` and a payment was recorded. Never an actual
    # refund transaction, just the figure that one is owed (gap-fix:
    # supplier-failure cancellation, docs/modules/purchase_orders.md).
    refundable_amount: Decimal = Decimal("0.0000")
    payment_status: str
    lines: list[FinanceLineOut]
    payments: list[FinancePaymentOut]
