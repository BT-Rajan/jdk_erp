"""Controlled Opening Stock (gap-fix, no redesign): a new
opening_stock_entries table backs the one-time, IN-only movement that
establishes a (raw material, warehouse) pair's verified physical stock
when it's first brought under this ledger's control.

Its UNIQUE(raw_material_id, warehouse_id) is the actual duplicate-
protection mechanism required (rule 7): a second opening-stock
submission for the same pair collides on inserting *this* row, not on
the reference_id every StockMovement's own reference trivially has.
reference_type="opening_stock" / reference_id=this table's own row id is
what every OPENING_STOCK StockMovement writes -- the same reference
shape a RECEIPT movement already uses to point at its own
PurchaseOrderReceiptLine, and ADJUSTMENT at its own InventoryAdjustment.

No change to stock_movements' own schema: `opening_stock` is simply a
new value its existing movement_type column already accepts
(Python-level validated set, not a DB enum -- see
app/models/inventory.py).

Revision ID: 0042
Revises: 0041
Create Date: 2026-09-25

"""
from alembic import op
import sqlalchemy as sa

revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "opening_stock_entries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "organisation_id",
            sa.Integer(),
            sa.ForeignKey(
                "organisations.id", ondelete="RESTRICT", name="fk_opening_stock_entries_organisation_id_organisations"
            ),
            nullable=False,
        ),
        sa.Column(
            "raw_material_id",
            sa.Integer(),
            sa.ForeignKey("raw_materials.id", ondelete="RESTRICT", name="fk_opening_stock_entries_raw_material_id_raw_materials"),
            nullable=False,
        ),
        sa.Column(
            "warehouse_id",
            sa.Integer(),
            sa.ForeignKey("warehouses.id", ondelete="RESTRICT", name="fk_opening_stock_entries_warehouse_id_warehouses"),
            nullable=False,
        ),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.UniqueConstraint(
            "raw_material_id", "warehouse_id", name="uq_opening_stock_entries_raw_material_id_warehouse_id"
        ),
    )
    op.create_index("ix_opening_stock_entries_organisation_id", "opening_stock_entries", ["organisation_id"])
    op.create_index("ix_opening_stock_entries_raw_material_id", "opening_stock_entries", ["raw_material_id"])
    op.create_index("ix_opening_stock_entries_warehouse_id", "opening_stock_entries", ["warehouse_id"])


def downgrade() -> None:
    op.drop_index("ix_opening_stock_entries_warehouse_id", table_name="opening_stock_entries")
    op.drop_index("ix_opening_stock_entries_raw_material_id", table_name="opening_stock_entries")
    op.drop_index("ix_opening_stock_entries_organisation_id", table_name="opening_stock_entries")
    op.drop_table("opening_stock_entries")
