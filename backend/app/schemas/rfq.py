from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.rfq import CANCELLED, ISSUED, PRIORITY_NORMAL, REJECTED, RFQ_PRIORITIES, SELECTED
from app.schemas.file import FileOut


def _strip_or_none(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _check_priority(value: str) -> str:
    if value not in RFQ_PRIORITIES:
        raise ValueError(f"priority must be one of {RFQ_PRIORITIES}.")
    return value


class RfqLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    raw_material_id: int
    quantity: Decimal
    remarks: str | None


class RfqResponseLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    rfq_line_id: int
    unit_price: Decimal
    delivery_days: int | None
    remarks: str | None


class RfqResponseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    invitation_id: int
    response_received_at: datetime
    supplier_quotation_number: str | None
    quotation_date: date | None
    valid_until: date | None
    payment_terms: str | None
    delivery_terms: str | None
    freight_terms: str | None
    note: str | None
    created_by_user_id: int | None
    lines: list[RfqResponseLineOut] = []
    files: list[FileOut] = []


class RfqInvitationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    supplier_id: int
    status: str
    invited_at: datetime
    responses: list[RfqResponseOut] = []


class RfqOut(BaseModel):
    """`invitations[].responses[].lines` is the whole comparison shape
    (docs/modules/rfq.md #6) -- assembled from stored rows, never a
    computed ranking or total."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    organisation_id: int
    rfq_number: str
    status: str
    priority: str
    rfq_date: date
    required_delivery_date: date | None
    team_id: int | None
    requested_by_user_id: int | None
    notes: str | None
    cancel_reason: str | None
    decided_by_user_id: int | None
    decided_at: datetime | None
    decision_note: str | None
    selected_response_id: int | None
    purchase_order_id: int | None
    lines: list[RfqLineOut]
    invitations: list[RfqInvitationOut]


class RfqCreateRequest(BaseModel):
    """organisation_id, rfq_number and requested_by_user_id are never part
    of this payload -- all three are server-stamped (docs/modules/rfq.md
    #2/#10). Always starts `draft` with no lines and no invitations."""

    rfq_date: date
    required_delivery_date: date | None = None
    team_id: int | None = None
    priority: str = PRIORITY_NORMAL
    notes: str | None = None

    @field_validator("priority")
    @classmethod
    def _validate_priority(cls, value: str) -> str:
        return _check_priority(value)

    @model_validator(mode="after")
    def _check_dates(self) -> "RfqCreateRequest":
        if self.required_delivery_date is not None and self.required_delivery_date < self.rfq_date:
            raise ValueError("Required delivery date cannot be before the RFQ date.")
        return self


class RfqUpdateRequest(BaseModel):
    """Only meaningful while the RFQ is still `draft` -- enforced in
    app/api/rfqs.py, which also re-checks the date ordering against the
    stored values."""

    rfq_date: date | None = None
    required_delivery_date: date | None = None
    team_id: int | None = None
    priority: str | None = None
    notes: str | None = None

    @field_validator("rfq_date", "priority")
    @classmethod
    def _not_null(cls, value, info):
        if value is None:
            raise ValueError(f"{info.field_name} cannot be null.")
        return value

    @field_validator("priority")
    @classmethod
    def _validate_priority(cls, value: str) -> str:
        return _check_priority(value)


def _check_positive_quantity(value: Decimal) -> Decimal:
    if value <= 0:
        raise ValueError("Quantity must be greater than zero.")
    return value


class RfqLineCreateRequest(BaseModel):
    raw_material_id: int
    quantity: Decimal
    remarks: str | None = Field(default=None, max_length=2000)

    @field_validator("quantity")
    @classmethod
    def _check_quantity(cls, value: Decimal) -> Decimal:
        return _check_positive_quantity(value)

    @field_validator("remarks")
    @classmethod
    def _strip_remarks(cls, value: str | None) -> str | None:
        return _strip_or_none(value)


class RfqLineUpdateRequest(BaseModel):
    """`raw_material_id` is immutable -- remove and re-add the line
    instead of repointing it."""

    quantity: Decimal | None = None
    remarks: str | None = Field(default=None, max_length=2000)

    @field_validator("quantity")
    @classmethod
    def _check_quantity(cls, value: Decimal | None) -> Decimal:
        if value is None:
            raise ValueError("Quantity cannot be null.")
        return _check_positive_quantity(value)

    @field_validator("remarks")
    @classmethod
    def _strip_remarks(cls, value: str | None) -> str | None:
        return _strip_or_none(value)


class RfqInvitationCreateRequest(BaseModel):
    supplier_id: int


class RfqStatusChangeRequest(BaseModel):
    """`status` must be `issued` or `cancelled` -- every other status is
    only ever a side effect of a real action (capture response, decide,
    convert), never a direct target of this endpoint
    (docs/modules/rfq.md #9)."""

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


class RfqResponseLineRequest(BaseModel):
    rfq_line_id: int
    unit_price: Decimal = Field(max_digits=14, decimal_places=4)
    delivery_days: int | None = Field(default=None, ge=0, le=3650)
    remarks: str | None = Field(default=None, max_length=2000)

    @field_validator("remarks")
    @classmethod
    def _strip_remarks(cls, value: str | None) -> str | None:
        return _strip_or_none(value)

    @field_validator("unit_price")
    @classmethod
    def _check_positive(cls, value: Decimal) -> Decimal:
        if value <= 0:
            raise ValueError("Unit price must be greater than zero.")
        return value


class RfqCaptureResponseRequest(BaseModel):
    """What one invited supplier offered, as structured lines
    (docs/modules/rfq.md #5). `lines` need not cover every RFQ line, but
    must quote at least one -- a supplier who quotes nothing is recorded
    by declining the invitation instead. `file_ids` are optional
    supporting evidence already uploaded via POST /api/files."""

    response_received_at: datetime | None = None
    supplier_quotation_number: str | None = Field(default=None, max_length=60)
    quotation_date: date | None = None
    valid_until: date | None = None
    payment_terms: str | None = Field(default=None, max_length=255)
    delivery_terms: str | None = Field(default=None, max_length=255)
    freight_terms: str | None = Field(default=None, max_length=255)
    note: str | None = Field(default=None, max_length=4000)
    lines: list[RfqResponseLineRequest] = Field(max_length=500)
    file_ids: list[int] = Field(default_factory=list, max_length=20)

    @field_validator("supplier_quotation_number", "payment_terms", "delivery_terms", "freight_terms", "note")
    @classmethod
    def _strip_text(cls, value: str | None) -> str | None:
        return _strip_or_none(value)

    @field_validator("lines")
    @classmethod
    def _check_lines(cls, value: list[RfqResponseLineRequest]) -> list[RfqResponseLineRequest]:
        if not value:
            raise ValueError("Quote a price for at least one line.")
        ids = [line.rfq_line_id for line in value]
        if len(set(ids)) != len(ids):
            raise ValueError("Each RFQ line can only be quoted once per response.")
        return value

    @model_validator(mode="after")
    def _check_dates(self) -> "RfqCaptureResponseRequest":
        if self.quotation_date and self.valid_until and self.valid_until < self.quotation_date:
            raise ValueError("Valid-until date cannot be before the quotation date.")
        return self


class RfqDecisionRequest(BaseModel):
    decision: str
    selected_response_id: int | None = None
    note: str | None = Field(default=None, max_length=4000)

    @field_validator("decision")
    @classmethod
    def _check_decision(cls, value: str) -> str:
        if value not in (SELECTED, REJECTED):
            raise ValueError(f"decision must be one of {(SELECTED, REJECTED)}.")
        return value


class RfqConvertLineRequest(BaseModel):
    """`unit_price` omitted -> defaults from the selected response's quote
    for this line (docs/modules/rfq.md #8)."""

    rfq_line_id: int
    unit_price: Decimal | None = Field(default=None, max_digits=14, decimal_places=4)

    @field_validator("unit_price")
    @classmethod
    def _check_positive(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and value <= 0:
            raise ValueError("Unit price must be greater than zero.")
        return value


class RfqConvertRequest(BaseModel):
    """`lines` omitted -> every RFQ line converts at the selected
    response's quoted price. `lines` given -> exactly those lines convert
    (a subset is allowed, as in v1), each at its override price or, when
    none is given, the quoted one."""

    warehouse_id: int
    lines: list[RfqConvertLineRequest] | None = Field(default=None, max_length=500)

    @field_validator("lines")
    @classmethod
    def _check_lines(cls, value: list[RfqConvertLineRequest] | None) -> list[RfqConvertLineRequest] | None:
        if value is None:
            return value
        if not value:
            raise ValueError("At least one line must be converted to the purchase order.")
        ids = [line.rfq_line_id for line in value]
        if len(set(ids)) != len(ids):
            raise ValueError("Each RFQ line can only be converted once per request.")
        return value
