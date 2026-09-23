"""add products table (docs/modules/products.md)

Revision ID: 0021
Revises: 0020
Create Date: 2026-09-23

"""
from alembic import op
import sqlalchemy as sa

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Unique constraints declared inline in create_table -- SQLite has no
    # ALTER-based way to add a constraint to an existing table, and this
    # table doesn't exist yet, so no batch mode is needed (see 0017_categories.py).
    op.create_table(
        "products",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "organisation_id",
            sa.Integer(),
            sa.ForeignKey("organisations.id", ondelete="RESTRICT", name="fk_products_organisation_id_organisations"),
            nullable=False,
        ),
        sa.Column("code", sa.String(length=30), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column(
            "category_id",
            sa.Integer(),
            sa.ForeignKey("categories.id", ondelete="RESTRICT", name="fk_products_category_id_categories"),
            nullable=False,
        ),
        sa.Column(
            "unit_of_measure_id",
            sa.Integer(),
            sa.ForeignKey(
                "units_of_measure.id", ondelete="RESTRICT", name="fk_products_unit_of_measure_id_units_of_measure"
            ),
            nullable=False,
        ),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("selling_price", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("manufacturing_lead_time_days", sa.Integer(), nullable=True),
        sa.Column("customer_lead_time_days", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("organisation_id", "code", name="uq_products_organisation_id_code"),
        sa.UniqueConstraint("organisation_id", "name", name="uq_products_organisation_id_name"),
    )
    op.create_index("ix_products_organisation_id", "products", ["organisation_id"])
    op.create_index("ix_products_category_id", "products", ["category_id"])
    op.create_index("ix_products_unit_of_measure_id", "products", ["unit_of_measure_id"])


def downgrade() -> None:
    op.drop_table("products")
