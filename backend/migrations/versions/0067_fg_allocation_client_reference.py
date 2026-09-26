"""FG allocation duplicate protection (Production audit)

fg_allocations.last_client_reference: the client reference of the last
allocate/release applied to a claim, so a retried request changes nothing.

Revision ID: 0067
Revises: 0066
Create Date: 2026-09-26

"""
from alembic import op
import sqlalchemy as sa

revision = "0067"
down_revision = "0066"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("fg_allocations") as batch:
        batch.add_column(sa.Column("last_client_reference", sa.String(length=64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("fg_allocations") as batch:
        batch.drop_column("last_client_reference")
