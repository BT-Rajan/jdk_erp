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
    # Production P1 lifecycle.
    fulfilled_at: datetime | None = None
    cancelled_at: datetime | None = None
    cancellation_reason: str | None = None


class ProductionRequirementRowOut(ProductionRequirementOut):
    """The Production view of one requirement (Production P1): the demand
    record plus its source and derived position. `quantity` is the
    shortfall recorded at hand-off (or after a confirmed Admin change);
    `outstanding_quantity` is the part the order line has not received
    yet -- demand, not a production instruction."""

    sales_order_number: str | None = None
    sales_order_status: str | None = None
    customer_name: str | None = None
    line_number: int | None = None
    product_name: str | None = None
    ordered_quantity: Decimal | None = None
    covered_quantity: Decimal | None = None
    delivered_quantity: Decimal = Decimal("0")
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
