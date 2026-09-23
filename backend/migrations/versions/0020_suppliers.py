"""add suppliers table (docs/modules/suppliers.md)

Revision ID: 0020
Revises: 0019
Create Date: 2026-09-23

"""
from alembic import op
import sqlalchemy as sa

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Unique constraints declared inline in create_table -- SQLite has no
    # ALTER-based way to add a constraint to an existing table, and this
    # table doesn't exist yet, so no batch mode is needed (see 0017_categories.py).
    op.create_table(
        "suppliers",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "organisation_id",
            sa.Integer(),
            sa.ForeignKey("organisations.id", ondelete="RESTRICT", name="fk_suppliers_organisation_id_organisations"),
            nullable=False,
        ),
        sa.Column("code", sa.String(length=10), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("contact_person", sa.String(length=120), nullable=True),
        sa.Column("phone", sa.String(length=30), nullable=True),
        sa.Column("email", sa.String(length=120), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("organisation_id", "code", name="uq_suppliers_organisation_id_code"),
        sa.UniqueConstraint("organisation_id", "name", name="uq_suppliers_organisation_id_name"),
        sa.UniqueConstraint("organisation_id", "phone", name="uq_suppliers_organisation_id_phone"),
    )
    op.create_index("ix_suppliers_organisation_id", "suppliers", ["organisation_id"])


def downgrade() -> None:
    op.drop_table("suppliers")
