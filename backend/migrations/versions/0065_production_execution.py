"""Production Execution (P6)

production_executions (+ production_execution_materials): each posted
production event on a Production Order -- actual quantity, when, by whom
-- with the raw materials consumed, each referenced by exactly one
PRODUCTION_ISSUE stock movement, and the Finished Goods receipt movement.
production_orders gains the execution states and who/when started.

Revision ID: 0065
Revises: 0064
Create Date: 2026-09-26

"""
from alembic import op
import sqlalchemy as sa

revision = "0065"
down_revision = "0064"
branch_labels = None
depends_on = None

_CHECK = "ck_production_orders_status_valid"


def _fk(target: str, name: str, ondelete: str) -> sa.ForeignKey:
    return sa.ForeignKey(target, ondelete=ondelete, name=name)


def upgrade() -> None:
    with op.batch_alter_table("production_orders") as batch:
        batch.drop_constraint(_CHECK, type_="check")
        batch.create_check_constraint(
            _CHECK, "status IN ('draft', 'issued', 'in_progress', 'partially_completed', 'completed', 'cancelled')"
        )
        batch.add_column(sa.Column("started_at", sa.DateTime(), nullable=True))
        batch.add_column(
            sa.Column("started_by_user_id", sa.Integer(), _fk("users.id", "fk_production_orders_started_by_user_id", "SET NULL"), nullable=True)
        )
    op.create_table(
        "production_executions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organisation_id", sa.Integer(), _fk("organisations.id", "fk_production_executions_organisation_id_organisations", "RESTRICT"), nullable=False),
        sa.Column("production_order_id", sa.Integer(), _fk("production_orders.id", "fk_production_executions_order_id", "RESTRICT"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("produced_quantity", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column("unit_of_measure_id", sa.Integer(), _fk("units_of_measure.id", "fk_production_executions_unit_of_measure_id", "RESTRICT"), nullable=False),
        sa.Column("executed_at", sa.DateTime(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("client_reference", sa.String(length=64), nullable=True),
        sa.Column("recorded_by_user_id", sa.Integer(), _fk("users.id", "fk_production_executions_recorded_by_user_id", "SET NULL"), nullable=True),
        sa.Column("fg_movement_id", sa.Integer(), _fk("finished_goods_movements.id", "fk_production_executions_fg_movement_id", "RESTRICT"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("production_order_id", "sequence", name="uq_production_executions_order_sequence"),
        sa.UniqueConstraint("organisation_id", "client_reference", name="uq_production_executions_org_client_reference"),
        sa.CheckConstraint("produced_quantity > 0", name="ck_production_executions_produced_quantity_positive"),
        sa.CheckConstraint("sequence >= 1", name="ck_production_executions_sequence_positive"),
    )
    op.create_index("ix_production_executions_organisation_id", "production_executions", ["organisation_id"])
    op.create_index("ix_production_executions_production_order_id", "production_executions", ["production_order_id"])
    op.create_table(
        "production_execution_materials",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("production_execution_id", sa.Integer(), _fk("production_executions.id", "fk_production_execution_materials_execution_id", "CASCADE"), nullable=False),
        sa.Column("raw_material_id", sa.Integer(), _fk("raw_materials.id", "fk_production_execution_materials_raw_material_id", "RESTRICT"), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column("unit_of_measure_id", sa.Integer(), _fk("units_of_measure.id", "fk_production_execution_materials_unit_of_measure_id", "RESTRICT"), nullable=False),
        sa.Column("stock_movement_id", sa.Integer(), _fk("stock_movements.id", "fk_production_execution_materials_stock_movement_id", "RESTRICT"), nullable=True),
        sa.UniqueConstraint("production_execution_id", "raw_material_id", name="uq_production_execution_materials_exec_material"),
        sa.CheckConstraint("quantity > 0", name="ck_production_execution_materials_quantity_positive"),
    )
    op.create_index("ix_production_execution_materials_production_execution_id", "production_execution_materials", ["production_execution_id"])


def downgrade() -> None:
    op.drop_table("production_execution_materials")
    op.drop_table("production_executions")
    with op.batch_alter_table("production_orders") as batch:
        batch.drop_constraint("fk_production_orders_started_by_user_id", type_="foreignkey")
        batch.drop_column("started_by_user_id")
        batch.drop_column("started_at")
        batch.drop_constraint(_CHECK, type_="check")
        batch.create_check_constraint(_CHECK, "status IN ('draft', 'issued', 'cancelled')")
