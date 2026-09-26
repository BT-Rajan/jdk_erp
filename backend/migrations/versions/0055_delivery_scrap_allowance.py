"""Delivery Scrap Allowance % (organisations.delivery_scrap_allowance_percent)

Organisation-level, Admin-set delivery tolerance, 0.00-999.99, default 0.
A future Delivery Instruction copies it when created; nothing else reads it.

Revision ID: 0055
Revises: 0054
Create Date: 2026-09-26

"""
from alembic import op
import sqlalchemy as sa

revision = "0055"
down_revision = "0054"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("organisations") as batch:
        batch.add_column(
            sa.Column("delivery_scrap_allowance_percent", sa.Numeric(precision=5, scale=2), nullable=False, server_default="0")
        )


def downgrade() -> None:
    with op.batch_alter_table("organisations") as batch:
        batch.drop_column("delivery_scrap_allowance_percent")
