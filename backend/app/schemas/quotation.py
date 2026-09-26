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
    lines: list[QuotationLineOut]


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
