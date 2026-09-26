from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.quotation import QuotationLineCreateRequest


def _required_reason(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("A reason is required.")
    return value


class SalesOrderLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    line_number: int
    product_id: int
    quantity: Decimal
    unit_of_measure_id: int
    unit_price: Decimal
    line_amount: Decimal


class SalesOrderOut(BaseModel):
    """`can_cancel` / `can_edit` are the server's answer for the caller;
    the UI never decides them."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    order_number: str
    quotation_id: int
    quotation_number: str | None = None
    customer_id: int
    customer_name: str | None = None
    order_date: date
    requested_delivery_date: date | None
    currency: str
    subtotal_amount: Decimal
    total_amount: Decimal
    status: str
    created_by_user_id: int | None
    cancelled_at: datetime | None
    cancelled_by_user_id: int | None
    cancellation_reason: str | None
    handed_off_at: datetime | None = None
    handed_off_by_user_id: int | None = None
    handoff_source: str | None = None
    created_at: datetime
    updated_at: datetime
    lines: list[SalesOrderLineOut]
    can_cancel: bool = False
    can_edit: bool = False


class SalesOrderCancelRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator("reason")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        return _required_reason(value)


class SalesOrderUpdateRequest(BaseModel):
    """Admin-only change to an open order (S13.1). The reason is mandatory
    and audited; only the fields sent change and `lines` replaces every
    line. Number, status, source quotation and amounts are never taken
    from the client."""

    reason: str = Field(min_length=1, max_length=2000)
    # Accepted only so a change can be refused explicitly (S13.5): the
    # customer is fixed to the source quotation's.
    customer_id: int | None = None
    requested_delivery_date: date | None = None
    lines: list[QuotationLineCreateRequest] | None = Field(default=None, min_length=1, max_length=200)

    @field_validator("reason")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        return _required_reason(value)
