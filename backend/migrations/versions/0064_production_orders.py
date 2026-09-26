"""Production Orders (P5)

production_orders: production work issued to the factory from a scheduled
Production Plan (draft / issued / cancelled), numbered YY2NNNN, with the
production basis snapshotted at issue (production_order_components). No
inventory movement.

Revision ID: 0064
Revises: 0063
Create Date: 2026-09-26

"""
from alembic import op
import sqlalchemy as sa

revision = "0064"
down_revision = "0063"
branch_labels = None
depends_on = None


def _fk(target: str, name: str, ondelete: str) -> sa.ForeignKey:
    return sa.ForeignKey(target, ondelete=ondelete, name=name)


def upgrade() -> None:
    op.create_table(
        "production_orders",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organisation_id", sa.Integer(), _fk("organisations.id", "fk_production_orders_organisation_id_organisations", "RESTRICT"), nullable=False),
        sa.Column("order_number", sa.String(length=20), nullable=False),
        sa.Column("production_plan_id", sa.Integer(), _fk("production_plans.id", "fk_production_orders_plan_id", "RESTRICT"), nullable=False),
        sa.Column("production_schedule_entry_id", sa.Integer(), _fk("production_schedule_entries.id", "fk_production_orders_schedule_entry_id", "RESTRICT"), nullable=False),
        sa.Column("product_id", sa.Integer(), _fk("products.id", "fk_production_orders_product_id", "RESTRICT"), nullable=False),
        sa.Column("unit_of_measure_id", sa.Integer(), _fk("units_of_measure.id", "fk_production_orders_unit_of_measure_id", "RESTRICT"), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column("machine_id", sa.Integer(), _fk("machines.id", "fk_production_orders_machine_id", "RESTRICT"), nullable=False),
        sa.Column("scheduled_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("bom_id", sa.Integer(), _fk("boms.id", "fk_production_orders_bom_id", "SET NULL"), nullable=True),
        sa.Column("bom_base_quantity", sa.Numeric(precision=14, scale=4), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), _fk("users.id", "fk_production_orders_created_by_user_id", "SET NULL"), nullable=True),
        sa.Column("issued_at", sa.DateTime(), nullable=True),
        sa.Column("issued_by_user_id", sa.Integer(), _fk("users.id", "fk_production_orders_issued_by_user_id", "SET NULL"), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(), nullable=True),
        sa.Column("cancellation_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("organisation_id", "order_number", name="uq_production_orders_organisation_id_order_number"),
        sa.CheckConstraint("quantity > 0", name="ck_production_orders_quantity_positive"),
        sa.CheckConstraint("status IN ('draft', 'issued', 'cancelled')", name="ck_production_orders_status_valid"),
    )
    for column in ("organisation_id", "production_plan_id", "production_schedule_entry_id", "product_id", "scheduled_date"):
        op.create_index(f"ix_production_orders_{column}", "production_orders", [column])
    op.create_table(
        "production_order_components",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("production_order_id", sa.Integer(), _fk("production_orders.id", "fk_production_order_components_order_id", "CASCADE"), nullable=False),
        sa.Column("raw_material_id", sa.Integer(), _fk("raw_materials.id", "fk_production_order_components_raw_material_id", "RESTRICT"), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column("unit_of_measure_id", sa.Integer(), _fk("units_of_measure.id", "fk_production_order_components_unit_of_measure_id", "RESTRICT"), nullable=False),
        sa.Column("required_quantity", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.UniqueConstraint("production_order_id", "raw_material_id", name="uq_production_order_components_order_material"),
        sa.CheckConstraint("quantity > 0", name="ck_production_order_components_quantity_positive"),
        sa.CheckConstraint("required_quantity > 0", name="ck_production_order_components_required_quantity_positive"),
    )
    op.create_index("ix_production_order_components_production_order_id", "production_order_components", ["production_order_id"])


def downgrade() -> None:
    op.drop_table("production_order_components")
    op.drop_table("production_orders")
