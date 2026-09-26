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
