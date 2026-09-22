"""add customers table (docs/modules/customers.md)

Revision ID: 0019
Revises: 0018
Create Date: 2026-09-22

"""
from alembic import op
import sqlalchemy as sa

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Unique constraints declared inline in create_table -- SQLite has no
    # ALTER-based way to add a constraint to an existing table, and this
    # table doesn't exist yet, so no batch mode is needed (see 0017_categories.py).
    op.create_table(
        "customers",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "organisation_id",
            sa.Integer(),
            sa.ForeignKey("organisations.id", ondelete="RESTRICT", name="fk_customers_organisation_id_organisations"),
            nullable=False,
        ),
        sa.Column("code", sa.String(length=10), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("contact_person", sa.String(length=120), nullable=True),
        sa.Column("phone", sa.String(length=30), nullable=True),
        sa.Column("email", sa.String(length=120), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column(
            "assigned_to_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL", name="fk_customers_assigned_to_user_id_users"),
            nullable=True,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("organisation_id", "code", name="uq_customers_organisation_id_code"),
        sa.UniqueConstraint("organisation_id", "phone", name="uq_customers_organisation_id_phone"),
    )
    op.create_index("ix_customers_organisation_id", "customers", ["organisation_id"])
    op.create_index("ix_customers_assigned_to_user_id", "customers", ["assigned_to_user_id"])


def downgrade() -> None:
    op.drop_table("customers")
