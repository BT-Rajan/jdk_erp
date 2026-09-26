"""Production Plans (P3 -- MRP / Production Planning)

production_plans: what to produce, how much and why -- for a Production
Requirement (customer demand) or independent production -- with its BOM
snapshot (production_plan_components). No inventory, no Production Order.

Revision ID: 0062
Revises: 0061
Create Date: 2026-09-26

"""
from alembic import op
import sqlalchemy as sa

revision = "0062"
down_revision = "0061"
branch_labels = None
depends_on = None


def _fk(target: str, name: str, ondelete: str) -> sa.ForeignKey:
    return sa.ForeignKey(target, ondelete=ondelete, name=name)


def upgrade() -> None:
    op.create_table(
        "production_plans",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organisation_id", sa.Integer(), _fk("organisations.id", "fk_production_plans_organisation_id_organisations", "RESTRICT"), nullable=False),
        sa.Column("product_id", sa.Integer(), _fk("products.id", "fk_production_plans_product_id", "RESTRICT"), nullable=False),
        sa.Column("unit_of_measure_id", sa.Integer(), _fk("units_of_measure.id", "fk_production_plans_unit_of_measure_id", "RESTRICT"), nullable=False),
        sa.Column("planned_quantity", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column("original_quantity", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column("source_type", sa.String(length=20), nullable=False),
        sa.Column("production_requirement_id", sa.Integer(), _fk("production_requirements.id", "fk_production_plans_requirement_id", "RESTRICT"), nullable=True),
        sa.Column("additional", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("required_by_date", sa.Date(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("bom_id", sa.Integer(), _fk("boms.id", "fk_production_plans_bom_id", "SET NULL"), nullable=True),
        sa.Column("bom_base_quantity", sa.Numeric(precision=14, scale=4), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), _fk("users.id", "fk_production_plans_created_by_user_id", "SET NULL"), nullable=True),
        sa.Column("planned_at", sa.DateTime(), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(), nullable=True),
        sa.Column("cancellation_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("planned_quantity > 0", name="ck_production_plans_planned_quantity_positive"),
        sa.CheckConstraint("original_quantity > 0", name="ck_production_plans_original_quantity_positive"),
        sa.CheckConstraint("source_type IN ('customer_demand', 'independent')", name="ck_production_plans_source_type_valid"),
        sa.CheckConstraint("status IN ('draft', 'planned', 'cancelled')", name="ck_production_plans_status_valid"),
        sa.CheckConstraint(
            "(source_type = 'customer_demand' AND production_requirement_id IS NOT NULL) "
            "OR (source_type = 'independent' AND production_requirement_id IS NULL)",
            name="ck_production_plans_source_reference",
        ),
    )
    op.create_index("ix_production_plans_organisation_id", "production_plans", ["organisation_id"])
    op.create_index("ix_production_plans_product_id", "production_plans", ["product_id"])
    op.create_index("ix_production_plans_production_requirement_id", "production_plans", ["production_requirement_id"])
    op.create_table(
        "production_plan_components",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("production_plan_id", sa.Integer(), _fk("production_plans.id", "fk_production_plan_components_plan_id", "CASCADE"), nullable=False),
        sa.Column("raw_material_id", sa.Integer(), _fk("raw_materials.id", "fk_production_plan_components_raw_material_id", "RESTRICT"), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column("unit_of_measure_id", sa.Integer(), _fk("units_of_measure.id", "fk_production_plan_components_unit_of_measure_id", "RESTRICT"), nullable=False),
    )
    op.create_index("ix_production_plan_components_production_plan_id", "production_plan_components", ["production_plan_id"])


def downgrade() -> None:
    op.drop_table("production_plan_components")
    op.drop_table("production_plans")
