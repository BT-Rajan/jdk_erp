from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import OrganisationScopedMixin, TimestampMixin

# Finished Goods' own ledger vocabulary -- deliberately separate from
# app/models/inventory.py's MOVEMENT_TYPES (RECEIPT/RECEIPT_REVERSAL/
# ADJUSTMENT/OPENING_STOCK, all Raw Material concepts). A Product's
# stock is never received by Procurement or opened with a starting
# balance the way a raw material is; it exists because it was made
# (PRODUCTION_COMPLETION, IN) and leaves because it was shipped
# (DELIVERY, OUT), with ADJUSTMENT as the same controlled, reasoned
# correction mechanism Raw Material Inventory already has. A validated
# Python tuple, not a DB enum, matching every other fixed-set column in
# this project (MOVEMENT_TYPES, BOM_STATUSES, PURCHASE_ORDER_STATUSES).
PRODUCTION_COMPLETION = "production_completion"
DELIVERY = "delivery"
ADJUSTMENT = "adjustment"
FINISHED_GOODS_MOVEMENT_TYPES = (PRODUCTION_COMPLETION, DELIVERY, ADJUSTMENT)

# Same generic (reference_type, reference_id) shape app/models/inventory.py's
# StockMovement already uses, for the same reason: a future Production
# Completion event and a future Delivery/Dispatch event each point at
# their own source document without this table growing a new FK column
# per source type. `ADJUSTMENT_REFERENCE` is what every Controlled
# Finished Goods Stock Adjustment writes, pointing at its own
# FinishedGoodsAdjustment row (below) -- the one place its mandatory
# reason lives, mirroring inventory.py's own ADJUSTMENT_REFERENCE shape
# exactly. There is deliberately no reference type constant here for
# production completion or delivery: no module in this codebase creates
# those events yet (see app/services/finished_goods_inventory_service.py's
# own module docstring), so their reference_type is simply whatever a
# future Production/Delivery module passes in, the same way RECEIPT's
# own reference_type was always caller-supplied.
ADJUSTMENT_REFERENCE = "finished_goods_adjustment"


class FinishedGoodsMovement(Base, OrganisationScopedMixin):
    """One immutable, append-only ledger row per Finished Goods
    stock-affecting event -- the Product/FinishedGoodsInventory
    equivalent of app/models/inventory.py's StockMovement, and the
    authoritative history a FinishedGoodsInventory snapshot is always
    derivable from. Never edited after creation (no `updated_at` -- a
    movement is a historical fact) and never deleted.

    A deliberately separate table from stock_movements, per this
    module's own founding rule: Finished Goods are Products, not Raw
    Materials, and must never share a ledger, a balance table, or a
    unique-pair identity with Raw Material Inventory -- even though the
    two tables are structurally identical, mixing rows for two different
    entity types (raw_material_id vs product_id) into one table would
    make "what is this row's stock item" ambiguous and would have forced
    a change to the existing, already-audited stock_movements schema.

    Written exclusively by app/services/finished_goods_inventory_service.py
    -- no module outside this one ever inserts a row here directly, the
    same "one authoritative stock ledger" rule already binding for
    stock_movements, applied to its own separate Finished Goods ledger."""

    __tablename__ = "finished_goods_movements"
    __table_args__ = (
        Index("ix_finished_goods_movements_reference_type_reference_id", "reference_type", "reference_id"),
        # Mirrors stock_movements' own uq_stock_movements_reference_type_
        # reference_id_movement_type exactly: a given source event can
        # post at most one movement of a given kind here too -- the
        # duplicate-source-transaction guard rule 4 requires, built in
        # from this table's first migration rather than added later as a
        # hardening pass.
        UniqueConstraint(
            "reference_type", "reference_id", "movement_type",
            name="uq_finished_goods_movements_reference_type_reference_id_movement_type",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    movement_type: Mapped[str] = mapped_column(String(20), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    # The unit `quantity` above is expressed in -- always the product's
    # own stock unit (Product.unit_of_measure_id) at the moment this row
    # was written. Recorded explicitly, the same "self-describing ledger
    # row, never re-derived later" reasoning stock_movements.unit_of_measure_id
    # already established, so a historical movement's quantity and unit
    # always stay paired even if a later change altered what a Product's
    # current unit is.
    unit_of_measure_id: Mapped[int] = mapped_column(
        ForeignKey("units_of_measure.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    reference_type: Mapped[str] = mapped_column(String(30), nullable=False)
    reference_id: Mapped[int] = mapped_column(nullable=False)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)


class FinishedGoodsInventory(Base, TimestampMixin, OrganisationScopedMixin):
    """The current-quantity snapshot per (Product, Warehouse) -- always
    derivable from FinishedGoodsMovement, kept as a materialized
    snapshot purely so a read doesn't have to sum the whole ledger every
    time, the exact same reasoning and shape as app/models/inventory.py's
    RawMaterialInventory. Written exclusively by
    app/services/finished_goods_inventory_service.py, via the same
    atomic conditional-UPDATE shape RawMaterialInventory's own writer
    already established -- never edited directly by any other module."""

    __tablename__ = "finished_goods_inventory"
    __table_args__ = (
        UniqueConstraint("product_id", "warehouse_id", name="uq_finished_goods_inventory_product_id_warehouse_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    quantity_on_hand: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False, default=0, server_default="0")


class FinishedGoodsAdjustment(Base, OrganisationScopedMixin):
    """Why a Controlled Finished Goods Stock Adjustment was made --
    everything else it needs (product, warehouse, quantity, unit,
    direction via the quantity's own sign, who, when) already lives on
    its own FinishedGoodsMovement row (movement_type=ADJUSTMENT,
    reference_type=ADJUSTMENT_REFERENCE, reference_id=this row's id);
    this table exists only to give that movement a reference target and
    hold the one required fact it doesn't already carry -- the mandatory
    reason. Mirrors app/models/inventory.py's InventoryAdjustment
    exactly, subject to the same "same controlled-adjustment principles"
    this module's own spec requires. Never edited or deleted: a wrong
    adjustment is corrected by a new, opposite adjustment, never by
    changing this row."""

    __tablename__ = "finished_goods_adjustments"

    id: Mapped[int] = mapped_column(primary_key=True)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
