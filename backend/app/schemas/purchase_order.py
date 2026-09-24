from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.purchase_order import CANCELLED, DEFAULT_CURRENCY, DRAFT
from app.schemas.file import FileOut


def _strip_or_none(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _check_currency(value: str) -> str:
    value = value.strip().upper()
    if len(value) != 3 or not value.isalpha():
        raise ValueError("Currency must be a 3-letter code, e.g. KWD.")
    return value


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
    lines: list[PurchaseOrderReceiptLineOut] = []
    documents: list[FileOut] = []


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
    paid_amount: Decimal
    outstanding_amount: Decimal
    payment_status: str
    lines: list[PurchaseOrderLineOut]
    revisions: list[PurchaseOrderRevisionOut]
    documents: list[FileOut]
    payments: list[PurchaseOrderPaymentOut]
    receipts: list[PurchaseOrderReceiptOut]


class PurchaseOrderCreateRequest(BaseModel):
    """PO header (docs/modules/purchase_orders.md #2). `po_number` and
    `order_date` (today) are server-stamped. Items are added afterward
    via POST .../lines; at least one is required to submit for approval.
    `rfq_id` is only ever set by the RFQ's PO-generation step."""

    supplier_id: int
    warehouse_id: int
    expected_delivery_date: date
    payment_terms: str = Field(min_length=1, max_length=200)
    currency: str = DEFAULT_CURRENCY
    supplier_reference: str | None = Field(default=None, max_length=100)
    delivery_instructions: str | None = Field(default=None, max_length=2000)
    notes: str | None = Field(default=None, max_length=4000)

    @field_validator("payment_terms")
    @classmethod
    def _check_payment_terms(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Payment terms are required.")
        return value

    @field_validator("currency")
    @classmethod
    def _validate_currency(cls, value: str) -> str:
        return _check_currency(value)

    @field_validator("supplier_reference", "delivery_instructions", "notes")
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        return _strip_or_none(value)


class PurchaseOrderUpdateRequest(BaseModel):
    """Draft-only (enforced in app/api/purchase_orders.py).
    `supplier_id`/`warehouse_id`/`rfq_id` are immutable."""

    expected_delivery_date: date | None = None
    payment_terms: str | None = Field(default=None, max_length=200)
    currency: str | None = None
    supplier_reference: str | None = Field(default=None, max_length=100)
    delivery_instructions: str | None = Field(default=None, max_length=2000)
    notes: str | None = Field(default=None, max_length=4000)

    @field_validator("expected_delivery_date", "payment_terms", "currency")
    @classmethod
    def _not_null(cls, value, info):
        if value is None or (isinstance(value, str) and not value.strip()):
            raise ValueError(f"{info.field_name} is required.")
        return value.strip() if isinstance(value, str) else value

    @field_validator("currency")
    @classmethod
    def _validate_currency(cls, value: str) -> str:
        return _check_currency(value)

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
    payment_date: date
    amount: Decimal
    payment_method: str | None = None
    reference_number: str | None = None
    notes: str | None = None
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
