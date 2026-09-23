"""every master's code becomes system-generated and required (docs/modules/categories.md #4)

Revision ID: 0026
Revises: 0025
Create Date: 2026-09-23

"""
from alembic import op
import sqlalchemy as sa

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # categories.code was the one master still optional/caller-editable
    # -- every other Phase 2 master (Customer, Supplier, Product, Raw
    # Material, Production Line, Machine, Warehouse) already requires a
    # code today, so only this column's nullability actually changes
    # here. Any existing NULL is backfilled with a placeholder,
    # unique-per-row value first -- required for SQLite to accept the
    # NOT NULL rewrite below, and harmless in practice since this
    # column's whole purpose (a system-generated code) is being
    # introduced in this same release; a fresh install never sees a NULL
    # here at all.
    op.execute("UPDATE categories SET code = 'LEGACY-' || id WHERE code IS NULL")
    with op.batch_alter_table("categories") as batch_op:
        batch_op.alter_column("code", existing_type=sa.String(length=30), nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("categories") as batch_op:
        batch_op.alter_column("code", existing_type=sa.String(length=30), nullable=True)
