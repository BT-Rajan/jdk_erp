"""add categories table (docs/modules/categories.md)

Revision ID: 0017
Revises: 0016
Create Date: 2026-09-22

"""
from alembic import op
import sqlalchemy as sa

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Unique constraints declared inline in create_table -- SQLite has no
    # ALTER-based way to add a constraint to an existing table, and this
    # table doesn't exist yet, so no batch mode is needed (see 0004_teams.py).
    op.create_table(
        "categories",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "organisation_id",
            sa.Integer(),
            sa.ForeignKey("organisations.id", ondelete="RESTRICT", name="fk_categories_organisation_id_organisations"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("code", sa.String(length=30), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("organisation_id", "name", name="uq_categories_organisation_id_name"),
        sa.UniqueConstraint("organisation_id", "code", name="uq_categories_organisation_id_code"),
    )
    op.create_index("ix_categories_organisation_id", "categories", ["organisation_id"])


def downgrade() -> None:
    op.drop_table("categories")
