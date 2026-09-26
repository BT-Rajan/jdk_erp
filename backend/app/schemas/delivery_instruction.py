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
    scrap_allowance_percent: Decimal
    max_permitted_quantity: Decimal


class DeliveryInstructionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    delivery_number: str
    sales_order_id: int
    sales_order_number: str | None = None
    customer_id: int
    customer_name: str | None = None
    status: str
    created_by_user_id: int | None
    created_at: datetime
    lines: list[DeliveryInstructionLineOut]
