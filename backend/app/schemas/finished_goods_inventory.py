from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator

IN_STOCK = "in_stock"
OUT_OF_STOCK = "out_of_stock"
NO_RECORD = "no_record"


class FinishedGoodsStockPositionOut(BaseModel):
    """One row of the Stock Position screen -- Product, category, stock
    UOM, warehouse, quantity on hand, active/inactive status and a
    simple stock status, per this view's own field list. `status` is a
    plain three-value read: `no_record` for a Product with no Finished
    Goods movement anywhere yet (never received/produced/adjusted --
    genuinely distinct from a ledger that exists and nets to zero),
    `out_of_stock` once a real ledger's quantity_on_hand reaches zero
    (it can never go negative -- rule 4), `in_stock` otherwise. No
    reorder point/minimum-stock concept exists on Product, so there is
    no fourth "low stock" state to compute (rule 9: no scope
    expansion). `warehouse_id`/`warehouse_name`/`quantity_on_hand` are
    only null for a `no_record` row -- no movement has ever named a
    warehouse for that Product, so there is nothing to report a
    warehouse-scoped quantity against; inventing a zero balance across
    every warehouse would misrepresent a Product that simply hasn't
    been produced, delivered or adjusted yet."""

    product_id: int
    product_code: str
    product_name: str
    product_is_active: bool
    category_id: int
    category_name: str
    warehouse_id: int | None
    warehouse_name: str | None
    unit_of_measure_id: int
    unit_code: str
    quantity_on_hand: Decimal | None
    status: str


class FinishedGoodsMovementOut(BaseModel):
    """One row of a Finished Good's movement history -- rule 6's own
    field list: date/time, movement type, quantity IN/OUT, resulting
    balance, reference/source, user."""

    id: int
    movement_type: str
    quantity: Decimal
    unit_of_measure_id: int
    unit_code: str
    resulting_balance: Decimal
    reference_type: str
    reference_id: int
    created_by_user_id: int | None
    created_by_name: str | None
    created_at: datetime


class AdjustFinishedGoodsStockRequest(BaseModel):
    """Mirrors app/schemas/inventory.py's AdjustStockRequest exactly,
    for a Product instead of a Raw Material -- `quantity`'s own sign is
    the adjustment's direction (positive = stock in, negative = stock
    out). No unit_of_measure_id field -- the product's own current
    stock unit is resolved server-side, never accepted as caller
    input."""

    product_id: int
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
            raise ValueError("A reason is required to adjust Finished Goods stock.")
        return value.strip()


class FinishedGoodsAdjustmentOut(BaseModel):
    """The created adjustment's own record, plus the resulting balance
    -- mirrors app/schemas/inventory.py's AdjustmentOut exactly."""

    id: int
    product_id: int
    product_name: str
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
