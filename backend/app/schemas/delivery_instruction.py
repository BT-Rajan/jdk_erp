from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.file import FileOut


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
    quantity_override_reason: str | None = None
    pallet_count_default: int | None = None
    pallet_count: int | None = None
    pallet_count_manual: bool = False


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
    fulfilled_at: datetime | None = None
    fulfilled_by_user_id: int | None = None
    not_fulfilled_reason: str | None = None
    not_fulfilled_at: datetime | None = None
    created_by_user_id: int | None
    created_at: datetime
    lines: list[DeliveryInstructionLineOut]
    # The latest Delivery Note (detail responses only).
    pdf_file: FileOut | None = None


class DeliveryLinePositionOut(BaseModel):
    """One Sales Order line's cumulative delivery position (derived)."""

    model_config = ConfigDict(from_attributes=True)

    sales_order_line_id: int
    product_id: int
    unit_of_measure_id: int
    ordered_quantity: Decimal
    fulfilled_quantity: Decimal
    remaining_quantity: Decimal
    ceiling_quantity: Decimal
    remaining_permitted_quantity: Decimal


class DeliveryPositionOut(BaseModel):
    sales_order_id: int
    sales_order_number: str
    sales_order_status: str
    customer_name: str | None = None
    requested_delivery_date: date | None = None
    # Whether a new Delivery Instruction may be created now (server rule).
    can_create: bool = False
    scrap_allowance_percent: Decimal
    # False until the order's first Delivery Instruction locks the %.
    allowance_locked: bool
    lines: list[DeliveryLinePositionOut]


class DeliveryShipmentUpdateRequest(BaseModel):
    """A pending line's shipment quantity and/or pallets (Delivery D3).
    Omitting `pallet_count` keeps a warehouse-set count (or follows the
    default); sending null returns it to the default."""

    quantity: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=4)
    # Optional check: if sent, it must be the line's stock unit.
    unit_of_measure_id: int | None = None
    pallet_count: int | None = Field(default=None, ge=1, strict=True)
    # Required when an Admin sets a quantity above the remaining permitted.
    override_reason: str | None = Field(default=None, max_length=2000)


class DeliveryNotFulfilledRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


class DeliverableOrderOut(BaseModel):
    """A Sales Order that can take a Delivery Instruction now."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    order_number: str
    customer_name: str | None = None
    requested_delivery_date: date | None = None
    status: str
