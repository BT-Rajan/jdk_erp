from datetime import date, datetime
from decimal import Decimal

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
    created_at: datetime
    updated_at: datetime
    lines: list[QuotationLineOut]
