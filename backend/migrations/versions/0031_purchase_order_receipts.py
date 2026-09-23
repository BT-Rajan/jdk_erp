"""goods receipts against a purchase order
(docs/modules/purchase_orders.md, Revision 4)

Revision ID: 0031
Revises: 0030
Create Date: 2026-09-23

"""
from alembic import op
import sqlalchemy as sa

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "purchase_order_receipts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "organisation_id",
            sa.Integer(),
            sa.ForeignKey(
                "organisations.id", ondelete="RESTRICT", name="fk_purchase_order_receipts_organisation_id_organisations"
            ),
            nullable=False,
        ),
        sa.Column("receipt_number", sa.String(length=20), nullable=False),
        sa.Column(
            "purchase_order_id",
            sa.Integer(),
            sa.ForeignKey(
                "purchase_orders.id", ondelete="CASCADE", name="fk_purchase_order_receipts_purchase_order_id_purchase_orders"
            ),
            nullable=False,
        ),
        sa.Column(
            "warehouse_id",
            sa.Integer(),
            sa.ForeignKey("warehouses.id", ondelete="RESTRICT", name="fk_purchase_order_receipts_warehouse_id_warehouses"),
            nullable=False,
        ),
        sa.Column("receipt_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False, server_default="draft"),
        sa.Column("supplier_delivery_reference", sa.String(length=120), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("posted_at", sa.DateTime(), nullable=True),
        sa.Column(
            "posted_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL", name="fk_purchase_order_receipts_posted_by_user_id_users"),
            nullable=True,
        ),
        sa.Column("cancelled_at", sa.DateTime(), nullable=True),
        sa.Column(
            "cancelled_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL", name="fk_purchase_order_receipts_cancelled_by_user_id_users"),
            nullable=True,
        ),
        sa.Column("reversed_at", sa.DateTime(), nullable=True),
        sa.Column(
            "reversed_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL", name="fk_purchase_order_receipts_reversed_by_user_id_users"),
            nullable=True,
        ),
        sa.Column("reversal_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL", name="fk_purchase_order_receipts_created_by_user_id_users"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "organisation_id", "receipt_number", name="uq_purchase_order_receipts_organisation_id_receipt_number"
        ),
    )
    op.create_index("ix_purchase_order_receipts_organisation_id", "purchase_order_receipts", ["organisation_id"])
    op.create_index("ix_purchase_order_receipts_purchase_order_id", "purchase_order_receipts", ["purchase_order_id"])
    op.create_index("ix_purchase_order_receipts_warehouse_id", "purchase_order_receipts", ["warehouse_id"])

    op.create_table(
        "purchase_order_receipt_lines",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "receipt_id",
            sa.Integer(),
            sa.ForeignKey(
                "purchase_order_receipts.id",
                ondelete="CASCADE",
                name="fk_purchase_order_receipt_lines_receipt_id_purchase_order_receipts",
            ),
            nullable=False,
        ),
        sa.Column(
            "purchase_order_line_id",
            sa.Integer(),
            sa.ForeignKey(
                "purchase_order_lines.id",
                ondelete="RESTRICT",
                name="fk_purchase_order_receipt_lines_purchase_order_line_id_purchase_order_lines",
            ),
            nullable=False,
        ),
        sa.Column(
            "raw_material_id",
            sa.Integer(),
            sa.ForeignKey(
                "raw_materials.id", ondelete="RESTRICT", name="fk_purchase_order_receipt_lines_raw_material_id_raw_materials"
            ),
            nullable=False,
        ),
        sa.Column("quantity", sa.Numeric(precision=14, scale=4), nullable=False),
    )
    op.create_index("ix_purchase_order_receipt_lines_receipt_id", "purchase_order_receipt_lines", ["receipt_id"])
    op.create_index(
        "ix_purchase_order_receipt_lines_purchase_order_line_id", "purchase_order_receipt_lines", ["purchase_order_line_id"]
    )
    op.create_index("ix_purchase_order_receipt_lines_raw_material_id", "purchase_order_receipt_lines", ["raw_material_id"])


def downgrade() -> None:
    op.drop_table("purchase_order_receipt_lines")
    op.drop_table("purchase_order_receipts")
