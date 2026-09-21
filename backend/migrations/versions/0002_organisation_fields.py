"""expand organisations: code, contact details, address, currency, timezone, is_active

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-21

"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("organisations") as batch_op:
        batch_op.add_column(sa.Column("code", sa.String(length=20), nullable=False, server_default=""))
        batch_op.add_column(sa.Column("contact_email", sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column("contact_phone", sa.String(length=30), nullable=True))
        batch_op.add_column(sa.Column("address", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("currency", sa.String(length=3), nullable=False, server_default=""))
        batch_op.add_column(sa.Column("timezone", sa.String(length=64), nullable=False, server_default="UTC"))
        batch_op.add_column(sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.create_unique_constraint("uq_organisations_code", ["code"])

    # The "" server defaults above exist only to satisfy NOT NULL while
    # backfilling any pre-existing rows; they're otherwise inert since the
    # ORM model (app/models/organisation.py) never relies on them -- the
    # application always sets code/currency explicitly. Dropping a column
    # default isn't portable enough across SQLite/MySQL to bother with
    # (SQLite has no ALTER COLUMN ... DROP DEFAULT at all outside batch
    # mode), so they're left in place rather than stripped here.


def downgrade() -> None:
    with op.batch_alter_table("organisations") as batch_op:
        batch_op.drop_constraint("uq_organisations_code", type_="unique")
        batch_op.drop_column("is_active")
        batch_op.drop_column("timezone")
        batch_op.drop_column("currency")
        batch_op.drop_column("address")
        batch_op.drop_column("contact_phone")
        batch_op.drop_column("contact_email")
        batch_op.drop_column("code")
