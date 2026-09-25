from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator


class AdjustStockRequest(BaseModel):
    """`quantity`'s own sign is the adjustment's direction -- positive is
    stock in, negative is stock out (docs/modules/purchase_orders.md's
    own "movement_type alone determines direction" reasoning, extended
    here since a plain ADJUSTMENT movement_type can go either way, unlike
    RECEIPT/RECEIPT_REVERSAL). No unit_of_measure_id field -- the raw
    material's own current stock unit is resolved server-side and is
    never accepted as caller input (gap-fix: Controlled Stock
    Adjustments -- UOM, no arbitrary unit entry)."""

    raw_material_id: int
    warehouse_id: int
    quantity: Decimal = Field(max_digits=14, decimal_places=4)
    reason: str

    @field_validator("quantity")
    @classmethod
    def _check_nonzero(cls, value: Decimal) -> Decimal:
        if value == 0:
            raise ValueError("Adjustment quantity cannot be zero.")
        return value

    @field_validator("reason")
    @classmethod
    def _check_reason(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("A reason is required to adjust stock.")
        return value.strip()


class AdjustmentOut(BaseModel):
    """The created adjustment's own record, plus the resulting balance --
    confirmation that the correction landed, not a ledger/history view
    (no inventory dashboard, no adjustment listing, in this pass)."""

    id: int
    raw_material_id: int
    material_name: str
    warehouse_id: int
    warehouse_name: str
    quantity: Decimal
    unit_of_measure_id: int
    unit_code: str
    reason: str
    created_by_user_id: int | None
    created_by_name: str | None
    created_at: datetime
    quantity_on_hand: Decimal
