"""Quotation data foundation: product price range, quotations, quotation lines

Sales S4.

products.min_selling_price / max_selling_price -- the Admin-set permitted
quoting range, both optional (a product without a full range needs Admin
approval for any quoted price). Existing products are left with no range.

quotations -- header; quotation_number (YY4NNNN) unique per organisation.

quotation_lines -- product, quantity in the product's own unit, price,
server-calculated amount, and the price range the line was checked
against.

Revision ID: 0045
Revises: 0044
Create Date: 2026-09-26

"""
from alembic import op
import sqlalchemy as sa

revision = "0045"
down_revision = "0044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("products") as batch_op:
        batch_op.add_column(sa.Column("min_selling_price", sa.Numeric(precision=14, scale=2), nullable=True))
        batch_op.add_column(sa.Column("max_selling_price", sa.Numeric(precision=14, scale=2), nullable=True))

    op.create_table(
        "quotations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "organisation_id",
            sa.Integer(),
            sa.ForeignKey("organisations.id", ondelete="RESTRICT", name="fk_quotations_organisation_id_organisations"),
            nullable=False,
        ),
        sa.Column("quotation_number", sa.String(length=20), nullable=False),
        sa.Column(
            "customer_id",
            sa.Integer(),
            sa.ForeignKey("customers.id", ondelete="RESTRICT", name="fk_quotations_customer_id_customers"),
            nullable=False,
        ),
        sa.Column(
            "created_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL", name="fk_quotations_created_by_user_id_users"),
            nullable=True,
        ),
        sa.Column("quotation_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("subtotal_amount", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column("total_amount", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column("price_approval_required", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "organisation_id", "quotation_number", name="uq_quotations_organisation_id_quotation_number"
        ),
    )
    op.create_index("ix_quotations_organisation_id", "quotations", ["organisation_id"])
    op.create_index("ix_quotations_customer_id", "quotations", ["customer_id"])
    op.create_index("ix_quotations_created_by_user_id", "quotations", ["created_by_user_id"])

    op.create_table(
        "quotation_lines",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "quotation_id",
            sa.Integer(),
            sa.ForeignKey("quotations.id", ondelete="CASCADE", name="fk_quotation_lines_quotation_id_quotations"),
            nullable=False,
        ),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column(
            "product_id",
            sa.Integer(),
            sa.ForeignKey("products.id", ondelete="RESTRICT", name="fk_quotation_lines_product_id_products"),
            nullable=False,
        ),
        sa.Column("quantity", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column(
            "unit_of_measure_id",
            sa.Integer(),
            sa.ForeignKey(
                "units_of_measure.id", ondelete="RESTRICT", name="fk_quotation_lines_unit_of_measure_id_units_of_measure"
            ),
            nullable=False,
        ),
        sa.Column("unit_price", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column("line_amount", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column("min_selling_price", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("max_selling_price", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("price_approval_required", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("quotation_id", "line_number", name="uq_quotation_lines_quotation_id_line_number"),
    )
    op.create_index("ix_quotation_lines_quotation_id", "quotation_lines", ["quotation_id"])
    op.create_index("ix_quotation_lines_product_id", "quotation_lines", ["product_id"])
    op.create_index("ix_quotation_lines_unit_of_measure_id", "quotation_lines", ["unit_of_measure_id"])


def downgrade() -> None:
    op.drop_index("ix_quotation_lines_unit_of_measure_id", table_name="quotation_lines")
    op.drop_index("ix_quotation_lines_product_id", table_name="quotation_lines")
    op.drop_index("ix_quotation_lines_quotation_id", table_name="quotation_lines")
    op.drop_table("quotation_lines")
    op.drop_index("ix_quotations_created_by_user_id", table_name="quotations")
    op.drop_index("ix_quotations_customer_id", table_name="quotations")
    op.drop_index("ix_quotations_organisation_id", table_name="quotations")
    op.drop_table("quotations")
    with op.batch_alter_table("products") as batch_op:
        batch_op.drop_column("max_selling_price")
        batch_op.drop_column("min_selling_price")
