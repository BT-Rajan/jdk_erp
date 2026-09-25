"""Controlled Stock Adjustments (gap-fix, no redesign): a new
inventory_adjustments table holds the one required fact a Controlled
Stock Adjustment's own StockMovement row doesn't already carry -- its
mandatory reason. Everything else (material, warehouse, quantity, unit,
direction via the quantity's own sign, who, when) is recorded on that
StockMovement row exactly like a receipt is, via
reference_type="inventory_adjustment" / reference_id=this table's own
row id -- the same reference mechanism a RECEIPT movement's reference
already uses to point at its own PurchaseOrderReceiptLine.

No change to stock_movements' own schema: `adjustment` is simply a new
value its existing movement_type column already accepts (Python-level
validated set, not a DB enum -- see app/models/inventory.py), and it
already has everywhere else this needs (raw_material_id, warehouse_id,
quantity, unit_of_measure_id, reference_type, reference_id,
created_by_user_id, created_at).

Revision ID: 0041
Revises: 0040
Create Date: 2026-09-25

"""
from alembic import op
import sqlalchemy as sa

revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "inventory_adjustments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "organisation_id",
            sa.Integer(),
            sa.ForeignKey("organisations.id", ondelete="RESTRICT", name="fk_inventory_adjustments_organisation_id_organisations"),
            nullable=False,
        ),
        sa.Column("reason", sa.String(length=500), nullable=False),
    )
    op.create_index(
        "ix_inventory_adjustments_organisation_id", "inventory_adjustments", ["organisation_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_inventory_adjustments_organisation_id", table_name="inventory_adjustments")
    op.drop_table("inventory_adjustments")
