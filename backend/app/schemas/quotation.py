from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class QuotationLineCreateRequest(BaseModel):
    """`unit_of_measure_id` is required and must be the product's own unit
    -- stated explicitly, never assumed, and never converted."""

    product_id: int
    quantity: Decimal = Field(max_digits=14, decimal_places=4)
    unit_of_measure_id: int
    unit_price: Decimal = Field(max_digits=14, decimal_places=4)

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


class QuotationCreateRequest(BaseModel):
    """No number, date, status, currency, owner or amounts: all are set
    server-side. Any such field a client sends is ignored."""

    customer_id: int
    lines: list[QuotationLineCreateRequest] = Field(min_length=1, max_length=200)
    # Optional; checked server-side not to be before today (Kuwait).
    requested_delivery_date: date | None = None


class QuotationUpdateRequest(BaseModel):
    """Controlled edit (Sales S10). Only the fields sent change; `lines`
    replaces every line. Number, date, status, currency, owner, amounts,
    readiness and approvals are never accepted from the client."""

    customer_id: int | None = None
    requested_delivery_date: date | None = None
    lines: list[QuotationLineCreateRequest] | None = Field(default=None, min_length=1, max_length=200)


class QuotationLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    line_number: int
    product_id: int
    quantity: Decimal
    unit_of_measure_id: int
    unit_price: Decimal
    line_amount: Decimal
    min_selling_price: Decimal | None
    max_selling_price: Decimal | None
    price_approval_required: bool


class QuotationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    quotation_number: str
    customer_id: int
    created_by_user_id: int | None
    quotation_date: date
    status: str
    currency: str
    subtotal_amount: Decimal
    total_amount: Decimal
    price_approval_required: bool
    requested_delivery_date: date | None
    same_day_override_decision: str | None
    same_day_override_reason: str | None
    same_day_override_by_user_id: int | None
    same_day_override_at: datetime | None
    created_at: datetime
    updated_at: datetime
    customer_name: str | None = None
    created_by_name: str | None = None
    lines: list[QuotationLineOut]


class QuotationListRowOut(QuotationOut):
    """A list row with the server's current readiness, so a list never
    derives it in the browser."""

    delivery_window: str | None = None
    readiness_status: str | None = None


class SameDayShortageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    product_id: int
    requested: Decimal
    available: Decimal


class SameDayGateOut(BaseModel):
    """`applies` is False (and `decision` null) unless the requested
    delivery date classifies as same_day right now."""

    model_config = ConfigDict(from_attributes=True)

    delivery_window: str | None
    applies: bool
    decision: str | None
    shortages: list[SameDayShortageOut]


class SameDayOverrideRequest(BaseModel):
    decision: Literal["approved", "rejected"]
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator("reason")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("A reason is required.")
        return value


class FeasibilityStageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    stage: str
    status: str
    reason_codes: list[str]
    details: list[str]


class FeasibilityCalculationOut(BaseModel):
    """`applies` is False unless the requested delivery date classifies
    as within_2_working_days right now."""

    model_config = ConfigDict(from_attributes=True)

    delivery_window: str | None
    applies: bool
    decision: str | None
    failed_stage: str | None
    reason_codes: list[str]
    working_days_available: int | None
    stages: list[FeasibilityStageOut]


class FeasibilityCheckLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    product_id: int
    quantity: Decimal
    unit_of_measure_id: int


class FeasibilityCheckOut(BaseModel):
    """A stored feasibility result (Sales S8). `result`, `failed_stage`,
    `reason_codes` and `stages` are the calculation as it was made;
    `state` and the decision fields carry the lifecycle. `is_current` is
    False once a newer check exists or the quotation's inputs changed."""

    id: int
    quotation_id: int
    customer_id: int
    requested_delivery_date: date
    delivery_window: str
    calculation_basis: str
    calculated_at: datetime
    result: str
    failed_stage: str | None
    reason_codes: list[str]
    stages: list[dict]
    state: str
    created_by_user_id: int | None
    created_at: datetime
    decision_reason: str | None
    decided_by_user_id: int | None
    decided_at: datetime | None
    lines: list[FeasibilityCheckLineOut]
    is_current: bool


class FeasibilityDecisionRequest(BaseModel):
    decision: Literal["approved", "rejected"]
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator("reason")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("A reason is required.")
        return value


class QuotationReadinessOut(BaseModel):
    """Readiness is a decision input, not acceptance (Sales S9). `status`
    is the most serious condition; `conditions` and `reason_codes` list
    everything that currently applies."""

    model_config = ConfigDict(from_attributes=True)

    status: str
    delivery_window: str | None
    conditions: list[str]
    reason_codes: list[str]
    feasibility_check_id: int | None
    feasibility_state: str | None
    commercial_approval_required: bool
