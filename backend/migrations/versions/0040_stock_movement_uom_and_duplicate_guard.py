"""Inventory ledger hardening (gap-fix, no redesign): every stock_movements
row now records the unit its quantity is expressed in, and a unique
constraint blocks the same source event from posting the same kind of
movement twice.

stock_movements.unit_of_measure_id -- backfilled from each row's raw
material's own (permanently frozen, since a StockMovement already exists
for it) unit_of_measure_id: the exact unit that already implicitly
applied to that historical quantity, made explicit -- never a
re-resolution against today's conversion setup, and no existing
quantity is touched.

uq_stock_movements_reference_type_reference_id_movement_type -- a given
source event (reference_type + reference_id) can post at most one
movement of a given kind (movement_type). A receipt and its later
reversal share the same reference but differ in movement_type, so a
legitimate reversal is unaffected; a second post of the same movement_type
for the same source is now rejected at the database level.

Revision ID: 0040
Revises: 0039
Create Date: 2026-09-25

"""
from alembic import op
import sqlalchemy as sa

revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("stock_movements") as batch_op:
        batch_op.add_column(sa.Column("unit_of_measure_id", sa.Integer(), nullable=True))

    op.execute(
        """
        UPDATE stock_movements
        SET unit_of_measure_id = (
            SELECT raw_materials.unit_of_measure_id
            FROM raw_materials
            WHERE raw_materials.id = stock_movements.raw_material_id
        )
        """
    )

    with op.batch_alter_table("stock_movements") as batch_op:
        batch_op.alter_column("unit_of_measure_id", existing_type=sa.Integer(), nullable=False)
        batch_op.create_foreign_key(
            "fk_stock_movements_unit_of_measure_id_units_of_measure",
            "units_of_measure",
            ["unit_of_measure_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_unique_constraint(
            "uq_stock_movements_reference_type_reference_id_movement_type",
            ["reference_type", "reference_id", "movement_type"],
        )
    op.create_index("ix_stock_movements_unit_of_measure_id", "stock_movements", ["unit_of_measure_id"])


def downgrade() -> None:
    op.drop_index("ix_stock_movements_unit_of_measure_id", table_name="stock_movements")
    with op.batch_alter_table("stock_movements") as batch_op:
        batch_op.drop_constraint("uq_stock_movements_reference_type_reference_id_movement_type", type_="unique")
        batch_op.drop_constraint("fk_stock_movements_unit_of_measure_id_units_of_measure", type_="foreignkey")
        batch_op.drop_column("unit_of_measure_id")
