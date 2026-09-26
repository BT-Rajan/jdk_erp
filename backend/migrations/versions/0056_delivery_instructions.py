"""Delivery Instructions -- shipment tranches of a Sales Order (Delivery D2)

delivery_instructions: number YY8NNNN unique per organisation, Sales Order,
customer, status (pending), creator, and the order's Delivery Scrap
Allowance % (copied from its first instruction). Several per Sales Order.
delivery_instruction_lines: Sales Order line, product, stock unit, ordered
quantity and this shipment's quantity. The permitted total is derived per
Sales Order, never stored per tranche.

Revision ID: 0056
Revises: 0055
Create Date: 2026-09-26

"""
from alembic import op
import sqlalchemy as sa

revision = "0056"
down_revision = "0055"
branch_labels = None
depends_on = None


def _fk(target: str, name: str, ondelete: str):
    return sa.ForeignKey(target, ondelete=ondelete, name=name)


def upgrade() -> None:
    op.create_table(
        "delivery_instructions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organisation_id", sa.Integer(), _fk("organisations.id", "fk_delivery_instructions_organisation_id_organisations", "RESTRICT"), nullable=False),
        sa.Column("delivery_number", sa.String(length=20), nullable=False),
        sa.Column("sales_order_id", sa.Integer(), _fk("sales_orders.id", "fk_delivery_instructions_sales_order_id_sales_orders", "RESTRICT"), nullable=False),
        sa.Column("customer_id", sa.Integer(), _fk("customers.id", "fk_delivery_instructions_customer_id_customers", "RESTRICT"), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("created_by_user_id", sa.Integer(), _fk("users.id", "fk_delivery_instructions_created_by_user_id_users", "SET NULL"), nullable=True),
        sa.Column("scrap_allowance_percent", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("organisation_id", "delivery_number", name="uq_delivery_instructions_organisation_id_delivery_number"),
    )
    op.create_index("ix_delivery_instructions_organisation_id", "delivery_instructions", ["organisation_id"])
    op.create_index("ix_delivery_instructions_sales_order_id", "delivery_instructions", ["sales_order_id"])
    op.create_index("ix_delivery_instructions_customer_id", "delivery_instructions", ["customer_id"])

    op.create_table(
        "delivery_instruction_lines",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("delivery_instruction_id", sa.Integer(), _fk("delivery_instructions.id", "fk_delivery_instruction_lines_instruction_id", "CASCADE"), nullable=False),
        sa.Column("sales_order_line_id", sa.Integer(), _fk("sales_order_lines.id", "fk_delivery_instruction_lines_sales_order_line_id", "RESTRICT"), nullable=False),
        sa.Column("product_id", sa.Integer(), _fk("products.id", "fk_delivery_instruction_lines_product_id_products", "RESTRICT"), nullable=False),
        sa.Column("unit_of_measure_id", sa.Integer(), _fk("units_of_measure.id", "fk_delivery_instruction_lines_unit_of_measure_id", "RESTRICT"), nullable=False),
        sa.Column("ordered_quantity", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.UniqueConstraint("delivery_instruction_id", "sales_order_line_id", name="uq_delivery_instruction_lines_instruction_line"),
        sa.CheckConstraint("quantity > 0", name="ck_delivery_instruction_lines_quantity_positive"),
    )
    op.create_index("ix_delivery_instruction_lines_delivery_instruction_id", "delivery_instruction_lines", ["delivery_instruction_id"])
    op.create_index("ix_delivery_instruction_lines_sales_order_line_id", "delivery_instruction_lines", ["sales_order_line_id"])


def downgrade() -> None:
    op.drop_index("ix_delivery_instruction_lines_sales_order_line_id", table_name="delivery_instruction_lines")
    op.drop_index("ix_delivery_instruction_lines_delivery_instruction_id", table_name="delivery_instruction_lines")
    op.drop_table("delivery_instruction_lines")
    op.drop_index("ix_delivery_instructions_customer_id", table_name="delivery_instructions")
    op.drop_index("ix_delivery_instructions_sales_order_id", table_name="delivery_instructions")
    op.drop_index("ix_delivery_instructions_organisation_id", table_name="delivery_instructions")
    op.drop_table("delivery_instructions")
