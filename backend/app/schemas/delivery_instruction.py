from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class DeliveryInstructionLineCreate(BaseModel):
    sales_order_line_id: int
    # Stock-unit quantity for this shipment; at most 4 decimal places
    # (like Sales Order lines) -- never rounded.
    quantity: Decimal = Field(gt=0, max_digits=14, decimal_places=4)


class DeliveryInstructionCreateRequest(BaseModel):
    sales_order_id: int
    lines: list[DeliveryInstructionLineCreate] = Field(min_length=1, max_length=200)


class DeliveryInstructionLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sales_order_line_id: int
    product_id: int
    unit_of_measure_id: int
    ordered_quantity: Decimal
    quantity: Decimal


class DeliveryInstructionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    delivery_number: str
    sales_order_id: int
    sales_order_number: str | None = None
    customer_id: int
    customer_name: str | None = None
    status: str
    # The Sales Order's allowance %, locked by its first instruction.
    scrap_allowance_percent: Decimal
    created_by_user_id: int | None
    created_at: datetime
    lines: list[DeliveryInstructionLineOut]


class DeliveryLinePositionOut(BaseModel):
    """One Sales Order line's cumulative delivery position (derived)."""

    model_config = ConfigDict(from_attributes=True)

    sales_order_line_id: int
    ordered_quantity: Decimal
    fulfilled_quantity: Decimal
    remaining_quantity: Decimal
    ceiling_quantity: Decimal
    remaining_permitted_quantity: Decimal


class DeliveryPositionOut(BaseModel):
    sales_order_id: int
    scrap_allowance_percent: Decimal
    # False until the order's first Delivery Instruction locks the %.
    allowance_locked: bool
    lines: list[DeliveryLinePositionOut]
