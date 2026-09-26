from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class ProductionRequirementComponentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    raw_material_id: int
    quantity: Decimal
    unit_of_measure_id: int


class ProductionRequirementOut(BaseModel):
    """Read-only (S15.2). `required_by_date` is the Sales Order's requested
    delivery date, read live -- never a copy."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    sales_order_id: int
    sales_order_line_id: int
    product_id: int
    quantity: Decimal
    unit_of_measure_id: int
    status: str
    required_by_date: date | None
    bom_id: int | None
    bom_base_quantity: Decimal | None
    components: list[ProductionRequirementComponentOut]
    created_at: datetime
    # Lifecycle.
    satisfied_at: datetime | None = None
    cancelled_at: datetime | None = None
    cancellation_reason: str | None = None


class ProductionRequirementRowOut(ProductionRequirementOut):
    """The Production view of one requirement: the demand record plus its
    source and live position. `required_quantity` = ordered - delivered;
    `allocated_quantity` = the line's FG claim; `outstanding_quantity` =
    the uncovered demand that may need production (the requirement's
    quantity while active, 0 once satisfied or cancelled) -- demand, not a
    production instruction. `covered_quantity` is the one-time hand-off
    figure, kept for history."""

    sales_order_number: str | None = None
    sales_order_status: str | None = None
    customer_name: str | None = None
    line_number: int | None = None
    product_name: str | None = None
    ordered_quantity: Decimal | None = None
    covered_quantity: Decimal | None = None
    delivered_quantity: Decimal = Decimal("0")
    required_quantity: Decimal = Decimal("0")
    allocated_quantity: Decimal = Decimal("0")
    outstanding_quantity: Decimal = Decimal("0")
    # The server's answer for the caller: may take the BOM snapshot now.
    can_resolve_bom: bool = False


class LineFulfilmentOut(BaseModel):
    """One Sales Order line's fulfilment result at hand-off."""

    model_config = ConfigDict(from_attributes=True)

    sales_order_line_id: int
    line_number: int | None = None
    unit_of_measure_id: int
    fg_available_quantity: Decimal
    fg_covered_quantity: Decimal
    production_quantity: Decimal
    result: str
    assessed_at: datetime
    production_requirement: ProductionRequirementOut | None = None
