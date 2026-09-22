"""add units_of_measure table (docs/modules/units_of_measure.md)

Revision ID: 0018
Revises: 0017
Create Date: 2026-09-22

"""
from alembic import op
import sqlalchemy as sa

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Unique constraints declared inline in create_table -- SQLite has no
    # ALTER-based way to add a constraint to an existing table, and this
    # table doesn't exist yet, so no batch mode is needed (see 0017_categories.py).
    op.create_table(
        "units_of_measure",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "organisation_id",
            sa.Integer(),
            sa.ForeignKey(
                "organisations.id", ondelete="RESTRICT", name="fk_units_of_measure_organisation_id_organisations"
            ),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("code", sa.String(length=20), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("organisation_id", "name", name="uq_units_of_measure_organisation_id_name"),
        sa.UniqueConstraint("organisation_id", "code", name="uq_units_of_measure_organisation_id_code"),
    )
    op.create_index("ix_units_of_measure_organisation_id", "units_of_measure", ["organisation_id"])


def downgrade() -> None:
    op.drop_table("units_of_measure")
