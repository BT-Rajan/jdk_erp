"""add raw_materials and supplier_materials tables (docs/modules/raw_materials.md)

Revision ID: 0022
Revises: 0021
Create Date: 2026-09-23

"""
from alembic import op
import sqlalchemy as sa

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Unique constraints declared inline in create_table -- SQLite has no
    # ALTER-based way to add a constraint to an existing table, and
    # neither table exists yet, so no batch mode is needed (see
    # 0017_categories.py).
    op.create_table(
        "raw_materials",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "organisation_id",
            sa.Integer(),
            sa.ForeignKey(
                "organisations.id", ondelete="RESTRICT", name="fk_raw_materials_organisation_id_organisations"
            ),
            nullable=False,
        ),
        sa.Column("code", sa.String(length=30), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column(
            "category_id",
            sa.Integer(),
            sa.ForeignKey("categories.id", ondelete="RESTRICT", name="fk_raw_materials_category_id_categories"),
            nullable=False,
        ),
        sa.Column(
            "unit_of_measure_id",
            sa.Integer(),
            sa.ForeignKey(
                "units_of_measure.id", ondelete="RESTRICT", name="fk_raw_materials_unit_of_measure_id_units_of_measure"
            ),
            nullable=False,
        ),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("reference_cost", sa.Numeric(precision=14, scale=4), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("organisation_id", "code", name="uq_raw_materials_organisation_id_code"),
        sa.UniqueConstraint("organisation_id", "name", name="uq_raw_materials_organisation_id_name"),
    )
    op.create_index("ix_raw_materials_organisation_id", "raw_materials", ["organisation_id"])
    op.create_index("ix_raw_materials_category_id", "raw_materials", ["category_id"])
    op.create_index("ix_raw_materials_unit_of_measure_id", "raw_materials", ["unit_of_measure_id"])

    op.create_table(
        "supplier_materials",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "supplier_id",
            sa.Integer(),
            sa.ForeignKey("suppliers.id", ondelete="CASCADE", name="fk_supplier_materials_supplier_id_suppliers"),
            nullable=False,
        ),
        sa.Column(
            "raw_material_id",
            sa.Integer(),
            sa.ForeignKey(
                "raw_materials.id", ondelete="CASCADE", name="fk_supplier_materials_raw_material_id_raw_materials"
            ),
            nullable=False,
        ),
        sa.Column("supplier_material_code", sa.String(length=60), nullable=True),
        sa.Column("purchase_price", sa.Numeric(precision=14, scale=4), nullable=True),
        sa.Column("lead_time_days", sa.Integer(), nullable=True),
        sa.Column("moq", sa.Numeric(precision=14, scale=4), nullable=True),
        sa.Column("max_supply_quantity", sa.Numeric(precision=14, scale=4), nullable=True),
        sa.Column("is_preferred", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("supplier_id", "raw_material_id", name="uq_supplier_materials_supplier_id_raw_material_id"),
    )
    op.create_index("ix_supplier_materials_supplier_id", "supplier_materials", ["supplier_id"])
    op.create_index("ix_supplier_materials_raw_material_id", "supplier_materials", ["raw_material_id"])


def downgrade() -> None:
    op.drop_table("supplier_materials")
    op.drop_table("raw_materials")
