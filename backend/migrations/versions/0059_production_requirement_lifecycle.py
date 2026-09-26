"""Production Requirement lifecycle (Production P1)

production_requirements gains when it was fulfilled or cancelled and the
cancellation reason. Status now also takes `fulfilled` and `cancelled`
(String(20), no enum change needed). Nothing existing is rewritten.

Revision ID: 0059
Revises: 0058
Create Date: 2026-09-26

"""
from alembic import op
import sqlalchemy as sa

revision = "0059"
down_revision = "0058"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("production_requirements") as batch:
        batch.add_column(sa.Column("fulfilled_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("cancelled_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("cancellation_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("production_requirements") as batch:
        batch.drop_column("cancellation_reason")
        batch.drop_column("cancelled_at")
        batch.drop_column("fulfilled_at")
