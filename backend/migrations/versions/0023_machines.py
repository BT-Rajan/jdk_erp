"""add production_lines and machines tables (docs/modules/machines.md)

Revision ID: 0023
Revises: 0022
Create Date: 2026-09-23

"""
from alembic import op
import sqlalchemy as sa

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Unique constraints declared inline in create_table -- SQLite has no
    # ALTER-based way to add a constraint to an existing table, and
    # neither table exists yet, so no batch mode is needed (see
    # 0017_categories.py).
    op.create_table(
        "production_lines",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "organisation_id",
            sa.Integer(),
            sa.ForeignKey(
                "organisations.id", ondelete="RESTRICT", name="fk_production_lines_organisation_id_organisations"
            ),
            nullable=False,
        ),
        sa.Column("code", sa.String(length=30), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("organisation_id", "code", name="uq_production_lines_organisation_id_code"),
        sa.UniqueConstraint("organisation_id", "name", name="uq_production_lines_organisation_id_name"),
    )
    op.create_index("ix_production_lines_organisation_id", "production_lines", ["organisation_id"])

    op.create_table(
        "machines",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "organisation_id",
            sa.Integer(),
            sa.ForeignKey("organisations.id", ondelete="RESTRICT", name="fk_machines_organisation_id_organisations"),
            nullable=False,
        ),
        sa.Column("code", sa.String(length=30), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column(
            "production_line_id",
            sa.Integer(),
            sa.ForeignKey(
                "production_lines.id", ondelete="RESTRICT", name="fk_machines_production_line_id_production_lines"
            ),
            nullable=False,
        ),
        sa.Column("capacity_quantity", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column(
            "capacity_unit_of_measure_id",
            sa.Integer(),
            sa.ForeignKey(
                "units_of_measure.id", ondelete="RESTRICT", name="fk_machines_capacity_unit_of_measure_id_units_of_measure"
            ),
            nullable=False,
        ),
        sa.Column("capacity_period_hours", sa.Numeric(precision=6, scale=2), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("organisation_id", "code", name="uq_machines_organisation_id_code"),
        sa.UniqueConstraint("organisation_id", "name", name="uq_machines_organisation_id_name"),
    )
    op.create_index("ix_machines_organisation_id", "machines", ["organisation_id"])
    op.create_index("ix_machines_production_line_id", "machines", ["production_line_id"])
    op.create_index("ix_machines_capacity_unit_of_measure_id", "machines", ["capacity_unit_of_measure_id"])


def downgrade() -> None:
    op.drop_table("machines")
    op.drop_table("production_lines")
