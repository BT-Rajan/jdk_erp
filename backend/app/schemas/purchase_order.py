from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from app.models.purchase_order import CANCELLED, DRAFT
from app.schemas.file import FileOut


class PurchaseOrderLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    raw_material_id: int
    quantity: Decimal
    unit_price: Decimal
    line_total: Decimal
    received_quantity: Decimal


class PurchaseOrderRevisionLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    raw_material_id: int
    quantity: Decimal
    unit_price: Decimal
    line_total: Decimal


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
    status: str
    revision_number: int
    order_date: date
    expected_delivery_date: date | None
    supplier_reference: str | None
    payment_terms: str | None
    notes: str | None
    cancel_reason: str | None
    supplier_confirmed_at: datetime | None
    supplier_confirmed_by_user_id: int | None
    supplier_confirmation_note: str | None
    total_amount: Decimal
    paid_amount: Decimal
    outstanding_amount: Decimal
    lines: list[PurchaseOrderLineOut]
    revisions: list[PurchaseOrderRevisionOut]
    documents: list[FileOut]
    payments: list[PurchaseOrderPaymentOut]
    receipts: list[PurchaseOrderReceiptOut]


class PurchaseOrderCreateRequest(BaseModel):
    """organisation_id and po_number are never part of this payload --
    po_number is system-generated (docs/modules/purchase_orders.md #21).
    Always starts `draft` and empty -- lines are added afterward via
    POST .../lines, the same add-relationship-after-creating-the-header
    pattern Bom/Machine already use. `rfq_id` is never client-supplied
    here either -- only app/api/rfqs.py's convert-to-PO action sets it
    (docs/modules/purchase_orders.md #22)."""

    supplier_id: int
    warehouse_id: int
    order_date: date
    expected_delivery_date: date | None = None
    supplier_reference: str | None = None
    payment_terms: str | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _check_dates(self) -> "PurchaseOrderCreateRequest":
        if self.expected_delivery_date is not None and self.expected_delivery_date < self.order_date:
            raise ValueError("Expected delivery date cannot be before the order date.")
        return self


class PurchaseOrderUpdateRequest(BaseModel):
    """`supplier_id`/`warehouse_id`/`rfq_id` are immutable -- sever and
    create a new PO instead of repointing one (docs/modules/purchase_orders.md
    #2). Only meaningful while the PO is still `draft` -- enforced in
    app/api/purchase_orders.py, not here."""

    order_date: date | None = None
    expected_delivery_date: date | None = None
    supplier_reference: str | None = None
    payment_terms: str | None = None
    notes: str | None = None


class PurchaseOrderLineCreateRequest(BaseModel):
    raw_material_id: int
    quantity: Decimal
    unit_price: Decimal | None = None

    @field_validator("quantity")
    @classmethod
    def _check_positive_quantity(cls, value: Decimal) -> Decimal:
        if value <= 0:
            raise ValueError("Quantity must be greater than zero.")
        return value

    @field_validator("unit_price")
    @classmethod
    def _check_positive_price(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and value <= 0:
            raise ValueError("Unit price must be greater than zero.")
        return value


class PurchaseOrderLineUpdateRequest(BaseModel):
    """`raw_material_id` is immutable -- remove and re-add the line
    instead of repointing it to a different material."""

    quantity: Decimal | None = None
    unit_price: Decimal | None = None

    @field_validator("quantity")
    @classmethod
    def _check_positive_quantity(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and value <= 0:
            raise ValueError("Quantity must be greater than zero.")
        return value

    @field_validator("unit_price")
    @classmethod
    def _check_positive_price(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and value <= 0:
            raise ValueError("Unit price must be greater than zero.")
        return value


class PurchaseOrderStatusChangeRequest(BaseModel):
    """`status` must be `draft` (reopen an issued PO for a new revision,
    "Create Revision" -- docs/modules/purchase_orders.md #23) or
    `cancelled`. Issuing has its own endpoint (POST .../issue) since it
    has real side effects (a revision snapshot) beyond a plain status
    flip; `supplier_confirmed`/`partially_received`/`fully_received` are
    never a direct target here either -- each is its own dedicated action.
    `cancel_reason` is required when cancelling, ignored otherwise."""

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


class ConfirmSupplierRequest(BaseModel):
    note: str | None = None
    file_ids: list[int] = []


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
