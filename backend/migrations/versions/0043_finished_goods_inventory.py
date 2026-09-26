"""Finished Goods Inventory foundation (new feature, no Raw Material
Inventory redesign): three new tables, deliberately separate from
stock_movements/raw_material_inventory/inventory_adjustments, mirroring
their exact shape for a Product instead of a Raw Material.

finished_goods_movements -- the append-only ledger (StockMovement's own
equivalent), including the duplicate-source-transaction guard
(uq_finished_goods_movements_reference_movement_type)
built in from this table's first migration, since Raw Material
Inventory only gained that guard later as a hardening pass (0040) --
Finished Goods Inventory starts with it already in place.

finished_goods_inventory -- the current-quantity snapshot per (Product,
Warehouse) pair (RawMaterialInventory's own equivalent).

finished_goods_adjustments -- the one required fact a Controlled
Finished Goods Stock Adjustment's own ledger row doesn't already carry:
its mandatory reason (InventoryAdjustment's own equivalent).

Revision ID: 0043
Revises: 0042
Create Date: 2026-09-25

"""
from alembic import op
import sqlalchemy as sa

revision = "0043"
down_revision = "0042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "finished_goods_movements",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "organisation_id",
            sa.Integer(),
            sa.ForeignKey(
                "organisations.id", ondelete="RESTRICT", name="fk_finished_goods_movements_organisation_id_organisations"
            ),
            nullable=False,
        ),
        sa.Column(
            "product_id",
            sa.Integer(),
            sa.ForeignKey("products.id", ondelete="RESTRICT", name="fk_finished_goods_movements_product_id_products"),
            nullable=False,
        ),
        sa.Column(
            "warehouse_id",
            sa.Integer(),
            sa.ForeignKey("warehouses.id", ondelete="RESTRICT", name="fk_finished_goods_movements_warehouse_id_warehouses"),
            nullable=False,
        ),
        sa.Column("movement_type", sa.String(length=20), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column(
            "unit_of_measure_id",
            sa.Integer(),
            sa.ForeignKey(
                "units_of_measure.id",
                ondelete="RESTRICT",
                name="fk_finished_goods_movements_unit_of_measure_id_units_of_measure",
            ),
            nullable=False,
        ),
        sa.Column("reference_type", sa.String(length=30), nullable=False),
        sa.Column("reference_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL", name="fk_finished_goods_movements_created_by_user_id_users"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "reference_type", "reference_id", "movement_type",
            name="uq_finished_goods_movements_reference_movement_type",
        ),
    )
    op.create_index("ix_finished_goods_movements_organisation_id", "finished_goods_movements", ["organisation_id"])
    op.create_index("ix_finished_goods_movements_product_id", "finished_goods_movements", ["product_id"])
    op.create_index("ix_finished_goods_movements_warehouse_id", "finished_goods_movements", ["warehouse_id"])
    op.create_index("ix_finished_goods_movements_unit_of_measure_id", "finished_goods_movements", ["unit_of_measure_id"])
    op.create_index("ix_finished_goods_movements_created_at", "finished_goods_movements", ["created_at"])
    op.create_index(
        "ix_finished_goods_movements_reference_type_reference_id",
        "finished_goods_movements",
        ["reference_type", "reference_id"],
    )

    op.create_table(
        "finished_goods_inventory",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "organisation_id",
            sa.Integer(),
            sa.ForeignKey(
                "organisations.id", ondelete="RESTRICT", name="fk_finished_goods_inventory_organisation_id_organisations"
            ),
            nullable=False,
        ),
        sa.Column(
            "product_id",
            sa.Integer(),
            sa.ForeignKey("products.id", ondelete="RESTRICT", name="fk_finished_goods_inventory_product_id_products"),
            nullable=False,
        ),
        sa.Column(
            "warehouse_id",
            sa.Integer(),
            sa.ForeignKey("warehouses.id", ondelete="RESTRICT", name="fk_finished_goods_inventory_warehouse_id_warehouses"),
            nullable=False,
        ),
        sa.Column("quantity_on_hand", sa.Numeric(precision=14, scale=4), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("product_id", "warehouse_id", name="uq_finished_goods_inventory_product_id_warehouse_id"),
    )
    op.create_index("ix_finished_goods_inventory_organisation_id", "finished_goods_inventory", ["organisation_id"])
    op.create_index("ix_finished_goods_inventory_product_id", "finished_goods_inventory", ["product_id"])
    op.create_index("ix_finished_goods_inventory_warehouse_id", "finished_goods_inventory", ["warehouse_id"])

    op.create_table(
        "finished_goods_adjustments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "organisation_id",
            sa.Integer(),
            sa.ForeignKey(
                "organisations.id", ondelete="RESTRICT", name="fk_finished_goods_adjustments_organisation_id_organisations"
            ),
            nullable=False,
        ),
        sa.Column("reason", sa.String(length=500), nullable=False),
    )
    op.create_index("ix_finished_goods_adjustments_organisation_id", "finished_goods_adjustments", ["organisation_id"])


def downgrade() -> None:
    op.drop_index("ix_finished_goods_adjustments_organisation_id", table_name="finished_goods_adjustments")
    op.drop_table("finished_goods_adjustments")

    op.drop_index("ix_finished_goods_inventory_warehouse_id", table_name="finished_goods_inventory")
    op.drop_index("ix_finished_goods_inventory_product_id", table_name="finished_goods_inventory")
    op.drop_index("ix_finished_goods_inventory_organisation_id", table_name="finished_goods_inventory")
    op.drop_table("finished_goods_inventory")

    op.drop_index("ix_finished_goods_movements_reference_type_reference_id", table_name="finished_goods_movements")
    op.drop_index("ix_finished_goods_movements_created_at", table_name="finished_goods_movements")
    op.drop_index("ix_finished_goods_movements_unit_of_measure_id", table_name="finished_goods_movements")
    op.drop_index("ix_finished_goods_movements_warehouse_id", table_name="finished_goods_movements")
    op.drop_index("ix_finished_goods_movements_product_id", table_name="finished_goods_movements")
    op.drop_index("ix_finished_goods_movements_organisation_id", table_name="finished_goods_movements")
    op.drop_table("finished_goods_movements")
