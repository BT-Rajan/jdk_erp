"""Production Requirements from handed-off Sales Orders (Sales S15.2)

sales_order_line_fulfilments -- per line: FG covered vs left to produce,
assessed once at hand-off.
production_requirements -- one per short line: quantity to produce in the
product's unit, status open / bom_required, active-BOM snapshot header.
production_requirement_components -- the BOM components as snapshotted.

Revision ID: 0053
Revises: 0052
Create Date: 2026-09-26

"""
from alembic import op
import sqlalchemy as sa

revision = "0053"
down_revision = "0052"
branch_labels = None
depends_on = None


def _fk(target: str, name: str, ondelete: str):
    return sa.ForeignKey(target, ondelete=ondelete, name=name)


def upgrade() -> None:
    op.create_table(
        "sales_order_line_fulfilments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organisation_id", sa.Integer(), _fk("organisations.id", "fk_sales_order_line_fulfilments_organisation_id_organisations", "RESTRICT"), nullable=False),
        sa.Column("sales_order_id", sa.Integer(), _fk("sales_orders.id", "fk_sales_order_line_fulfilments_sales_order_id_sales_orders", "RESTRICT"), nullable=False),
        sa.Column("sales_order_line_id", sa.Integer(), _fk("sales_order_lines.id", "fk_sales_order_line_fulfilments_sales_order_line_id", "RESTRICT"), nullable=False),
        sa.Column("unit_of_measure_id", sa.Integer(), _fk("units_of_measure.id", "fk_sales_order_line_fulfilments_unit_of_measure_id", "RESTRICT"), nullable=False),
        sa.Column("fg_available_quantity", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column("fg_covered_quantity", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column("production_quantity", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column("result", sa.String(length=20), nullable=False),
        sa.Column("assessed_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("sales_order_line_id", name="uq_sales_order_line_fulfilments_sales_order_line_id"),
        sa.CheckConstraint("fg_available_quantity >= 0", name="ck_sales_order_line_fulfilments_fg_available"),
        sa.CheckConstraint("fg_covered_quantity >= 0", name="ck_sales_order_line_fulfilments_fg_covered"),
        sa.CheckConstraint("production_quantity >= 0", name="ck_sales_order_line_fulfilments_production"),
    )
    op.create_index("ix_sales_order_line_fulfilments_organisation_id", "sales_order_line_fulfilments", ["organisation_id"])
    op.create_index("ix_sales_order_line_fulfilments_sales_order_id", "sales_order_line_fulfilments", ["sales_order_id"])

    op.create_table(
        "production_requirements",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organisation_id", sa.Integer(), _fk("organisations.id", "fk_production_requirements_organisation_id_organisations", "RESTRICT"), nullable=False),
        sa.Column("sales_order_id", sa.Integer(), _fk("sales_orders.id", "fk_production_requirements_sales_order_id_sales_orders", "RESTRICT"), nullable=False),
        sa.Column("sales_order_line_id", sa.Integer(), _fk("sales_order_lines.id", "fk_production_requirements_sales_order_line_id_sales_order_lines", "RESTRICT"), nullable=False),
        sa.Column("product_id", sa.Integer(), _fk("products.id", "fk_production_requirements_product_id_products", "RESTRICT"), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column("unit_of_measure_id", sa.Integer(), _fk("units_of_measure.id", "fk_production_requirements_unit_of_measure_id_units_of_measure", "RESTRICT"), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("bom_id", sa.Integer(), _fk("boms.id", "fk_production_requirements_bom_id_boms", "SET NULL"), nullable=True),
        sa.Column("bom_base_quantity", sa.Numeric(precision=14, scale=4), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("sales_order_line_id", name="uq_production_requirements_sales_order_line_id"),
        sa.CheckConstraint("quantity > 0", name="ck_production_requirements_quantity_positive"),
    )
    op.create_index("ix_production_requirements_organisation_id", "production_requirements", ["organisation_id"])
    op.create_index("ix_production_requirements_sales_order_id", "production_requirements", ["sales_order_id"])
    op.create_index("ix_production_requirements_product_id", "production_requirements", ["product_id"])

    op.create_table(
        "production_requirement_components",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("production_requirement_id", sa.Integer(), _fk("production_requirements.id", "fk_production_requirement_components_requirement_id", "CASCADE"), nullable=False),
        sa.Column("raw_material_id", sa.Integer(), _fk("raw_materials.id", "fk_production_requirement_components_raw_material_id", "RESTRICT"), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column("unit_of_measure_id", sa.Integer(), _fk("units_of_measure.id", "fk_production_requirement_components_unit_of_measure_id", "RESTRICT"), nullable=False),
        sa.UniqueConstraint("production_requirement_id", "raw_material_id", name="uq_production_requirement_components_requirement_material"),
    )
    op.create_index(
        "ix_production_requirement_components_production_requirement_id",
        "production_requirement_components",
        ["production_requirement_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_production_requirement_components_production_requirement_id", table_name="production_requirement_components")
    op.drop_table("production_requirement_components")
    op.drop_index("ix_production_requirements_product_id", table_name="production_requirements")
    op.drop_index("ix_production_requirements_sales_order_id", table_name="production_requirements")
    op.drop_index("ix_production_requirements_organisation_id", table_name="production_requirements")
    op.drop_table("production_requirements")
    op.drop_index("ix_sales_order_line_fulfilments_sales_order_id", table_name="sales_order_line_fulfilments")
    op.drop_index("ix_sales_order_line_fulfilments_organisation_id", table_name="sales_order_line_fulfilments")
    op.drop_table("sales_order_line_fulfilments")
