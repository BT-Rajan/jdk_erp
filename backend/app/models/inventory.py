from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import OrganisationScopedMixin, TimestampMixin

# A small, explicitly-validated set rather than a fixed DB enum, so a
# future Issue/Production movement type is a Python constant addition,
# not a migration. Mirrors BOM_STATUSES/PURCHASE_ORDER_STATUSES' own
# "validated tuple, not a DB-level enum" convention. `RECEIPT_REVERSAL`
# is added in Revision 4 (docs/modules/purchase_orders.md #38) for
# reversing a posted Goods Receipt -- a second, negative-quantity ledger
# row, never an edit of the original `RECEIPT` row. `ADJUSTMENT` (Controlled
# Stock Adjustments) is the explicit, manual correction mechanism for a
# verified physical/system stock difference -- its own quantity's sign is
# the adjustment's direction (positive = stock in, negative = stock out),
# so there is no separate direction column, the same reasoning
# RECEIPT_REVERSAL's own negative quantity already established.
# `OPENING_STOCK` (Controlled Opening Stock) is the one-time, IN-only
# movement that establishes the verified physical stock a (raw material,
# warehouse) pair starts with when it's first brought under this
# ledger's control -- always positive (never used to reduce stock; that's
# what ADJUSTMENT is for), and, unlike every other movement type here, is
# further guarded to at most one per (raw_material_id, warehouse_id) pair
# ever (see OpeningStockEntry below).
RECEIPT = "receipt"
RECEIPT_REVERSAL = "receipt_reversal"
ADJUSTMENT = "adjustment"
OPENING_STOCK = "opening_stock"
# Production Execution (P6): raw material consumed by recorded production --
# always OUT (negative), referencing the execution's material row.
PRODUCTION_ISSUE = "production_issue"
MOVEMENT_TYPES = (RECEIPT, RECEIPT_REVERSAL, ADJUSTMENT, OPENING_STOCK, PRODUCTION_ISSUE)

# Generic (reference_type, reference_id), not a hard FK, so a future
# Production/Sales movement can point at its own source document the same
# way without this table growing a new FK column per source type (the
# same reasoning app/models/audit_event.py's entity_type/entity_id pair
# already applies). `PURCHASE_ORDER_LINE_REFERENCE` is the reference type
# the old (now-removed) receive-as-action flow wrote -- kept only so
# already-written historical StockMovement rows keep their meaning; no
# code writes it anymore. `PURCHASE_ORDER_RECEIPT_LINE_REFERENCE`
# (Revision 4) is what every receipt-posting/reversal movement writes now,
# tracing a stock quantity to the receipt line -> receipt -> PO that
# produced it (docs/audit/PROCUREMENT_AUDIT.md Revision 4 #6).
# `ADJUSTMENT_REFERENCE` is what every Controlled Stock Adjustment writes,
# pointing at its own InventoryAdjustment row (below) -- the one place
# its mandatory reason lives, the same "a movement's reference points at
# whatever row explains it" shape the receipt reference already uses.
# `OPENING_STOCK_REFERENCE` is what every Controlled Opening Stock
# movement writes, pointing at its own OpeningStockEntry row (below).
PURCHASE_ORDER_LINE_REFERENCE = "purchase_order_line"
PURCHASE_ORDER_RECEIPT_LINE_REFERENCE = "purchase_order_receipt_line"
ADJUSTMENT_REFERENCE = "inventory_adjustment"
OPENING_STOCK_REFERENCE = "opening_stock"
PRODUCTION_EXECUTION_MATERIAL_REFERENCE = "production_execution_material"


class StockMovement(Base, OrganisationScopedMixin):
    """One immutable, append-only ledger row per stock-affecting event
    (docs/modules/purchase_orders.md #9) -- the authoritative history a
    RawMaterialInventory snapshot is always derivable from. Never edited
    after creation (no `updated_at` -- a movement is a historical fact,
    task's own "never silently rewrite historical receipts" rule) and
    never deleted.

    Written exclusively by app/services/inventory_service.py -- no module
    outside Inventory ever inserts a row here directly, the same "one
    authoritative stock ledger" rule docs/audit/WAREHOUSES_AUDIT.md #10/#11
    and docs/audit/RAW_MATERIALS_AUDIT.md #9 already documented as
    binding for whenever this table was built."""

    __tablename__ = "stock_movements"
    __table_args__ = (
        Index("ix_stock_movements_reference_type_reference_id", "reference_type", "reference_id"),
        # A given source event can post at most one movement of a given
        # kind -- e.g. one `receipt` and, separately, one `receipt_reversal`
        # for the same receipt line, but never two `receipt` rows for it
        # (gap-fix: Inventory ledger hardening). The single inventory-level
        # guard against a source movement being posted twice, never relying
        # on the caller alone.
        UniqueConstraint(
            "reference_type", "reference_id", "movement_type",
            name="uq_stock_movements_reference_type_reference_id_movement_type",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    raw_material_id: Mapped[int] = mapped_column(
        ForeignKey("raw_materials.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    movement_type: Mapped[str] = mapped_column(String(20), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    # The unit `quantity` above is expressed in -- always the raw
    # material's own stock unit at the moment this row was written (never
    # re-derived later: RawMaterial.unit_of_measure_id is permanently
    # frozen the instant any StockMovement exists for it, so this can
    # never drift from what it was when written). Recorded explicitly so
    # the ledger row is self-describing rather than relying on that
    # external freeze rule alone (gap-fix: Inventory ledger hardening --
    # movement UOM).
    unit_of_measure_id: Mapped[int] = mapped_column(
        ForeignKey("units_of_measure.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    reference_type: Mapped[str] = mapped_column(String(30), nullable=False)
    reference_id: Mapped[int] = mapped_column(nullable=False)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)


class RawMaterialInventory(Base, TimestampMixin, OrganisationScopedMixin):
    """The current-quantity snapshot per (Raw Material, Warehouse) --
    always derivable from StockMovement, kept as a materialized snapshot
    purely so a read doesn't have to sum the whole ledger every time
    (the same ledger-plus-snapshot shape docs/audit/RAW_MATERIALS_AUDIT.md
    #9 documented as jdk_clean's own real target design, extended here
    with the warehouse_id dimension jdk_clean never had). Written
    exclusively by app/services/inventory_service.py, via the same atomic
    conditional-UPDATE shape app/services/job_service.py's
    claim_pending_jobs already established in this codebase -- never
    edited directly by Purchase or any other module."""

    __tablename__ = "raw_material_inventory"
    __table_args__ = (
        UniqueConstraint("raw_material_id", "warehouse_id", name="uq_raw_material_inventory_raw_material_id_warehouse_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    raw_material_id: Mapped[int] = mapped_column(
        ForeignKey("raw_materials.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    quantity_on_hand: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False, default=0, server_default="0")


class InventoryAdjustment(Base, OrganisationScopedMixin):
    """Why a Controlled Stock Adjustment was made -- everything else it
    needs (material, warehouse, quantity, unit, direction via the
    quantity's own sign, who, when) already lives on its own StockMovement
    row (movement_type=ADJUSTMENT, reference_type=ADJUSTMENT_REFERENCE,
    reference_id=this row's id); this table exists only to give that
    movement a reference target and hold the one required fact it
    doesn't already carry -- the mandatory reason -- the same shape a
    PurchaseOrderReceiptLine already is for a RECEIPT movement's
    reference. Never edited or deleted, same as StockMovement itself: a
    wrong adjustment is corrected by a new, opposite adjustment, never by
    changing this row (docs/modules/purchase_orders.md #38's "reversal,
    never edit" rule, applied here too)."""

    __tablename__ = "inventory_adjustments"

    id: Mapped[int] = mapped_column(primary_key=True)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)


class OpeningStockEntry(Base, OrganisationScopedMixin):
    """The one-time record backing a Controlled Opening Stock movement --
    its own reason/description, and, via its UNIQUE(raw_material_id,
    warehouse_id), the actual duplicate-protection mechanism rule 7
    requires: this row's own insert is what a second opening-stock
    submission for the same pair collides on (caught the same way
    app/services/inventory_service._insert_movement already catches a
    duplicate StockMovement's own IntegrityError), not merely the
    already-unique reference_id every StockMovement's own reference
    trivially has. Everything else the movement needs (material,
    warehouse, quantity, unit, who, when) lives on its own StockMovement
    row (movement_type=OPENING_STOCK, reference_type=OPENING_STOCK_REFERENCE,
    reference_id=this row's id), the same shape InventoryAdjustment
    already is for ADJUSTMENT. Never edited or deleted: if stock later
    proves wrong, that's a Controlled Stock Adjustment, never a rewrite
    of this row."""

    __tablename__ = "opening_stock_entries"
    __table_args__ = (
        UniqueConstraint(
            "raw_material_id", "warehouse_id", name="uq_opening_stock_entries_raw_material_id_warehouse_id"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    raw_material_id: Mapped[int] = mapped_column(
        ForeignKey("raw_materials.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
