"""add purchase order and minimal stock ledger tables (docs/modules/purchase_orders.md)

Revision ID: 0027
Revises: 0026
Create Date: 2026-09-23

"""
from alembic import op
import sqlalchemy as sa

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # docs/modules/purchase_orders.md #4 -- draft/confirmed/
    # partially_received/fully_received/cancelled; partially_received/
    # fully_received are never a direct transition target, only a side
    # effect of receiving (app/services/purchase_order_service.py).
    op.create_table(
        "purchase_orders",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "organisation_id",
            sa.Integer(),
            sa.ForeignKey("organisations.id", ondelete="RESTRICT", name="fk_purchase_orders_organisation_id_organisations"),
            nullable=False,
        ),
        sa.Column("po_number", sa.String(length=20), nullable=False),
        sa.Column(
            "supplier_id",
            sa.Integer(),
            sa.ForeignKey("suppliers.id", ondelete="RESTRICT", name="fk_purchase_orders_supplier_id_suppliers"),
            nullable=False,
        ),
        sa.Column(
            "warehouse_id",
            sa.Integer(),
            sa.ForeignKey("warehouses.id", ondelete="RESTRICT", name="fk_purchase_orders_warehouse_id_warehouses"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("order_date", sa.Date(), nullable=False),
        sa.Column("expected_delivery_date", sa.Date(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("cancel_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("organisation_id", "po_number", name="uq_purchase_orders_organisation_id_po_number"),
    )
    op.create_index("ix_purchase_orders_organisation_id", "purchase_orders", ["organisation_id"])
    op.create_index("ix_purchase_orders_supplier_id", "purchase_orders", ["supplier_id"])
    op.create_index("ix_purchase_orders_warehouse_id", "purchase_orders", ["warehouse_id"])

    # No organisation_id of its own -- a child of an already
    # organisation-scoped PurchaseOrder, the same shape bom_components
    # already uses for Bom.
    op.create_table(
        "purchase_order_lines",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "purchase_order_id",
            sa.Integer(),
            sa.ForeignKey(
                "purchase_orders.id", ondelete="CASCADE", name="fk_purchase_order_lines_purchase_order_id_purchase_orders"
            ),
            nullable=False,
        ),
        sa.Column(
            "raw_material_id",
            sa.Integer(),
            sa.ForeignKey(
                "raw_materials.id", ondelete="RESTRICT", name="fk_purchase_order_lines_raw_material_id_raw_materials"
            ),
            nullable=False,
        ),
        sa.Column("quantity", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column("line_total", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column("received_quantity", sa.Numeric(precision=14, scale=4), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_purchase_order_lines_purchase_order_id", "purchase_order_lines", ["purchase_order_id"])
    op.create_index("ix_purchase_order_lines_raw_material_id", "purchase_order_lines", ["raw_material_id"])

    # Immutable, append-only ledger row per stock-affecting event
    # (docs/modules/purchase_orders.md #9) -- no updated_at, a movement is
    # a historical fact, never edited.
    op.create_table(
        "stock_movements",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "organisation_id",
            sa.Integer(),
            sa.ForeignKey("organisations.id", ondelete="RESTRICT", name="fk_stock_movements_organisation_id_organisations"),
            nullable=False,
        ),
        sa.Column(
            "raw_material_id",
            sa.Integer(),
            sa.ForeignKey("raw_materials.id", ondelete="RESTRICT", name="fk_stock_movements_raw_material_id_raw_materials"),
            nullable=False,
        ),
        sa.Column(
            "warehouse_id",
            sa.Integer(),
            sa.ForeignKey("warehouses.id", ondelete="RESTRICT", name="fk_stock_movements_warehouse_id_warehouses"),
            nullable=False,
        ),
        sa.Column("movement_type", sa.String(length=20), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column("reference_type", sa.String(length=30), nullable=False),
        sa.Column("reference_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL", name="fk_stock_movements_created_by_user_id_users"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_stock_movements_organisation_id", "stock_movements", ["organisation_id"])
    op.create_index("ix_stock_movements_raw_material_id", "stock_movements", ["raw_material_id"])
    op.create_index("ix_stock_movements_warehouse_id", "stock_movements", ["warehouse_id"])
    op.create_index("ix_stock_movements_created_at", "stock_movements", ["created_at"])
    op.create_index(
        "ix_stock_movements_reference_type_reference_id", "stock_movements", ["reference_type", "reference_id"]
    )

    # The current-quantity snapshot per (Raw Material, Warehouse) --
    # always derivable from stock_movements, kept as a materialized
    # snapshot so a read doesn't have to sum the whole ledger every time
    # (docs/audit/RAW_MATERIALS_AUDIT.md #9's target design).
    op.create_table(
        "raw_material_inventory",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "organisation_id",
            sa.Integer(),
            sa.ForeignKey(
                "organisations.id", ondelete="RESTRICT", name="fk_raw_material_inventory_organisation_id_organisations"
            ),
            nullable=False,
        ),
        sa.Column(
            "raw_material_id",
            sa.Integer(),
            sa.ForeignKey(
                "raw_materials.id", ondelete="RESTRICT", name="fk_raw_material_inventory_raw_material_id_raw_materials"
            ),
            nullable=False,
        ),
        sa.Column(
            "warehouse_id",
            sa.Integer(),
            sa.ForeignKey("warehouses.id", ondelete="RESTRICT", name="fk_raw_material_inventory_warehouse_id_warehouses"),
            nullable=False,
        ),
        sa.Column("quantity_on_hand", sa.Numeric(precision=14, scale=4), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "raw_material_id", "warehouse_id", name="uq_raw_material_inventory_raw_material_id_warehouse_id"
        ),
    )
    op.create_index("ix_raw_material_inventory_organisation_id", "raw_material_inventory", ["organisation_id"])
    op.create_index("ix_raw_material_inventory_raw_material_id", "raw_material_inventory", ["raw_material_id"])
    op.create_index("ix_raw_material_inventory_warehouse_id", "raw_material_inventory", ["warehouse_id"])


def downgrade() -> None:
    op.drop_table("raw_material_inventory")
    op.drop_table("stock_movements")
    op.drop_table("purchase_order_lines")
    op.drop_table("purchase_orders")
