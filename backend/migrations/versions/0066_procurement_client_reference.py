"""Procurement duplicate protection

purchase_order_receipts and purchase_order_payments gain client_reference
(unique per organisation, nullable): one reference per submission, so a
retried or repeated request returns the recorded receipt/payment instead
of posting stock or money twice. Existing rows stay NULL.

Revision ID: 0066
Revises: 0065
Create Date: 2026-09-26

"""
from alembic import op
import sqlalchemy as sa

revision = "0066"
down_revision = "0065"
branch_labels = None
depends_on = None

_TABLES = ("purchase_order_receipts", "purchase_order_payments")


def upgrade() -> None:
    for table in _TABLES:
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("client_reference", sa.String(length=64), nullable=True))
            batch.create_unique_constraint(f"uq_{table}_org_client_reference", ["organisation_id", "client_reference"])


def downgrade() -> None:
    for table in _TABLES:
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(f"uq_{table}_org_client_reference", type_="unique")
            batch.drop_column("client_reference")
