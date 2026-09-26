"""Delivery shipment quantity override and pallets (Delivery D3)

delivery_instruction_lines gains the Admin override reason for a shipment
quantity above the order's remaining permitted quantity, and pallet
counts: the system default, the count used, and whether the warehouse set
it manually. Pallets are handling information only.

Revision ID: 0057
Revises: 0056
Create Date: 2026-09-26

"""
from alembic import op
import sqlalchemy as sa

revision = "0057"
down_revision = "0056"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("delivery_instruction_lines") as batch:
        batch.add_column(sa.Column("quantity_override_reason", sa.Text(), nullable=True))
        batch.add_column(sa.Column("pallet_count_default", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("pallet_count", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("pallet_count_manual", sa.Boolean(), nullable=False, server_default="0"))
        batch.create_check_constraint("ck_delivery_instruction_lines_pallet_count_at_least_one", "pallet_count >= 1")


def downgrade() -> None:
    with op.batch_alter_table("delivery_instruction_lines") as batch:
        batch.drop_constraint("ck_delivery_instruction_lines_pallet_count_at_least_one", type_="check")
        batch.drop_column("pallet_count_manual")
        batch.drop_column("pallet_count")
        batch.drop_column("pallet_count_default")
        batch.drop_column("quantity_override_reason")
