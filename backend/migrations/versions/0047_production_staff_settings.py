"""Production staff settings for the 0-2 working-day manpower check

Sales S7. organisations.production_staff_available_per_day and
products.production_staff_required, both nullable and Admin-set; unset
values make the manpower check require an Admin decision.

Revision ID: 0047
Revises: 0046
Create Date: 2026-09-26

"""
from alembic import op
import sqlalchemy as sa

revision = "0047"
down_revision = "0046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("organisations") as batch_op:
        batch_op.add_column(sa.Column("production_staff_available_per_day", sa.Integer(), nullable=True))
    with op.batch_alter_table("products") as batch_op:
        batch_op.add_column(sa.Column("production_staff_required", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("products") as batch_op:
        batch_op.drop_column("production_staff_required")
    with op.batch_alter_table("organisations") as batch_op:
        batch_op.drop_column("production_staff_available_per_day")
