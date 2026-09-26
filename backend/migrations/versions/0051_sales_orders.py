"""Sales Orders (Sales S13)

sales_orders -- converted from one accepted quotation (unique
quotation_id); number YY6NNNN unique per organisation; open/cancelled.
sales_order_lines -- the quotation lines' commercial snapshot.
quotations.status (already String(20)) now also takes `converted`.

Revision ID: 0051
Revises: 0050
Create Date: 2026-09-26

"""
from alembic import op
import sqlalchemy as sa

revision = "0051"
down_revision = "0050"
branch_labels = None
depends_on = None


def _fk(target: str, name: str, ondelete: str):
    return sa.ForeignKey(target, ondelete=ondelete, name=name)


def upgrade() -> None:
    op.create_table(
        "sales_orders",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organisation_id", sa.Integer(), _fk("organisations.id", "fk_sales_orders_organisation_id_organisations", "RESTRICT"), nullable=False),
        sa.Column("order_number", sa.String(length=20), nullable=False),
        sa.Column("quotation_id", sa.Integer(), _fk("quotations.id", "fk_sales_orders_quotation_id_quotations", "RESTRICT"), nullable=False),
        sa.Column("customer_id", sa.Integer(), _fk("customers.id", "fk_sales_orders_customer_id_customers", "RESTRICT"), nullable=False),
        sa.Column("order_date", sa.Date(), nullable=False),
        sa.Column("requested_delivery_date", sa.Date(), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("subtotal_amount", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column("total_amount", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="open"),
        sa.Column("created_by_user_id", sa.Integer(), _fk("users.id", "fk_sales_orders_created_by_user_id_users", "SET NULL"), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(), nullable=True),
        sa.Column("cancelled_by_user_id", sa.Integer(), _fk("users.id", "fk_sales_orders_cancelled_by_user_id_users", "SET NULL"), nullable=True),
        sa.Column("cancellation_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("organisation_id", "order_number", name="uq_sales_orders_organisation_id_order_number"),
        sa.UniqueConstraint("quotation_id", name="uq_sales_orders_quotation_id"),
    )
    op.create_index("ix_sales_orders_organisation_id", "sales_orders", ["organisation_id"])
    op.create_index("ix_sales_orders_customer_id", "sales_orders", ["customer_id"])

    op.create_table(
        "sales_order_lines",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("sales_order_id", sa.Integer(), _fk("sales_orders.id", "fk_sales_order_lines_sales_order_id_sales_orders", "CASCADE"), nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), _fk("products.id", "fk_sales_order_lines_product_id_products", "RESTRICT"), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column(
            "unit_of_measure_id",
            sa.Integer(),
            _fk("units_of_measure.id", "fk_sales_order_lines_unit_of_measure_id_units_of_measure", "RESTRICT"),
            nullable=False,
        ),
        sa.Column("unit_price", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column("line_amount", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.UniqueConstraint("sales_order_id", "line_number", name="uq_sales_order_lines_sales_order_id_line_number"),
    )
    op.create_index("ix_sales_order_lines_sales_order_id", "sales_order_lines", ["sales_order_id"])
    op.create_index("ix_sales_order_lines_product_id", "sales_order_lines", ["product_id"])
    op.create_index("ix_sales_order_lines_unit_of_measure_id", "sales_order_lines", ["unit_of_measure_id"])


def downgrade() -> None:
    op.drop_index("ix_sales_order_lines_unit_of_measure_id", table_name="sales_order_lines")
    op.drop_index("ix_sales_order_lines_product_id", table_name="sales_order_lines")
    op.drop_index("ix_sales_order_lines_sales_order_id", table_name="sales_order_lines")
    op.drop_table("sales_order_lines")
    op.drop_index("ix_sales_orders_customer_id", table_name="sales_orders")
    op.drop_index("ix_sales_orders_organisation_id", table_name="sales_orders")
    op.drop_table("sales_orders")
