from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from app.models.rfq import CANCELLED, ISSUED, REJECTED, SELECTED
from app.schemas.file import FileOut


class RfqLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    raw_material_id: int
    quantity: Decimal


class RfqResponseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    response_received_at: datetime
    note: str | None
    created_by_user_id: int | None
    files: list[FileOut] = []


class RfqOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organisation_id: int
    rfq_number: str
    supplier_id: int
    status: str
    rfq_date: date
    required_delivery_date: date | None
    notes: str | None
    cancel_reason: str | None
    decided_by_user_id: int | None
    decided_at: datetime | None
    decision_note: str | None
    selected_response_id: int | None
    purchase_order_id: int | None
    lines: list[RfqLineOut]
    responses: list[RfqResponseOut]


class RfqCreateRequest(BaseModel):
    """organisation_id and rfq_number are never part of this payload --
    rfq_number is system-generated (docs/modules/rfq.md #7). Always
    starts `draft` and empty -- lines are added afterward via
    POST .../lines."""

    supplier_id: int
    rfq_date: date
    required_delivery_date: date | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _check_dates(self) -> "RfqCreateRequest":
        if self.required_delivery_date is not None and self.required_delivery_date < self.rfq_date:
            raise ValueError("Required delivery date cannot be before the RFQ date.")
        return self


class RfqUpdateRequest(BaseModel):
    """`supplier_id` is immutable (docs/modules/rfq.md #10). Only
    meaningful while the RFQ is still `draft` -- enforced in
    app/api/rfqs.py."""

    rfq_date: date | None = None
    required_delivery_date: date | None = None
    notes: str | None = None


class RfqLineCreateRequest(BaseModel):
    raw_material_id: int
    quantity: Decimal

    @field_validator("quantity")
    @classmethod
    def _check_positive(cls, value: Decimal) -> Decimal:
        if value <= 0:
            raise ValueError("Quantity must be greater than zero.")
        return value


class RfqLineUpdateRequest(BaseModel):
    """`raw_material_id` is immutable -- remove and re-add the line
    instead of repointing it."""

    quantity: Decimal

    @field_validator("quantity")
    @classmethod
    def _check_positive(cls, value: Decimal) -> Decimal:
        if value <= 0:
            raise ValueError("Quantity must be greater than zero.")
        return value


class RfqStatusChangeRequest(BaseModel):
    """`status` must be `issued` or `cancelled` -- every other status is
    only ever a side effect of a real action (capture response, decide,
    convert), never a direct target of this endpoint
    (docs/modules/rfq.md #3)."""

    status: str
    cancel_reason: str | None = None

    @field_validator("status")
    @classmethod
    def _check_status(cls, value: str) -> str:
        if value not in (ISSUED, CANCELLED):
            raise ValueError(f"status must be one of {(ISSUED, CANCELLED)}.")
        return value

    @model_validator(mode="after")
    def _check_cancel_reason(self) -> "RfqStatusChangeRequest":
        if self.status == CANCELLED:
            if not self.cancel_reason or not self.cancel_reason.strip():
                raise ValueError("cancel_reason is required when cancelling an RFQ.")
            self.cancel_reason = self.cancel_reason.strip()
        return self


class RfqCaptureResponseRequest(BaseModel):
    """`file_ids` are files already uploaded via POST /api/files (with no
    entity yet) that this call links to the new response
    (docs/modules/rfq.md #5/#15)."""

    response_received_at: datetime | None = None
    note: str | None = None
    file_ids: list[int]

    @field_validator("file_ids")
    @classmethod
    def _check_file_ids(cls, value: list[int]) -> list[int]:
        if not value:
            raise ValueError("At least one attachment is required to capture a response.")
        return value


class RfqDecisionRequest(BaseModel):
    decision: str
    selected_response_id: int | None = None
    note: str | None = None

    @field_validator("decision")
    @classmethod
    def _check_decision(cls, value: str) -> str:
        if value not in (SELECTED, REJECTED):
            raise ValueError(f"decision must be one of {(SELECTED, REJECTED)}.")
        return value


class RfqConvertLineRequest(BaseModel):
    rfq_line_id: int
    unit_price: Decimal

    @field_validator("unit_price")
    @classmethod
    def _check_positive(cls, value: Decimal) -> Decimal:
        if value <= 0:
            raise ValueError("Unit price must be greater than zero.")
        return value


class RfqConvertRequest(BaseModel):
    warehouse_id: int
    lines: list[RfqConvertLineRequest]

    @field_validator("lines")
    @classmethod
    def _check_lines(cls, value: list[RfqConvertLineRequest]) -> list[RfqConvertLineRequest]:
        if not value:
            raise ValueError("At least one line must be converted to the purchase order.")
        return value
