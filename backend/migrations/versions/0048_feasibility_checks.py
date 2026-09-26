"""Feasibility decision records (Sales S8)

feasibility_checks -- one row per calculation (first check or re-check),
never rewritten; Admin decision fields alongside the calculated result.
feasibility_check_lines -- the requested quantities the calculation used.

Revision ID: 0048
Revises: 0047
Create Date: 2026-09-26

"""
from alembic import op
import sqlalchemy as sa

revision = "0048"
down_revision = "0047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "feasibility_checks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "organisation_id",
            sa.Integer(),
            sa.ForeignKey(
                "organisations.id", ondelete="RESTRICT", name="fk_feasibility_checks_organisation_id_organisations"
            ),
            nullable=False,
        ),
        sa.Column(
            "quotation_id",
            sa.Integer(),
            sa.ForeignKey("quotations.id", ondelete="RESTRICT", name="fk_feasibility_checks_quotation_id_quotations"),
            nullable=False,
        ),
        sa.Column(
            "customer_id",
            sa.Integer(),
            sa.ForeignKey("customers.id", ondelete="RESTRICT", name="fk_feasibility_checks_customer_id_customers"),
            nullable=False,
        ),
        sa.Column("requested_delivery_date", sa.Date(), nullable=False),
        sa.Column("delivery_window", sa.String(length=30), nullable=False),
        sa.Column("calculation_basis", sa.String(length=40), nullable=False),
        sa.Column("calculated_at", sa.DateTime(), nullable=False),
        sa.Column("result", sa.String(length=30), nullable=False),
        sa.Column("failed_stage", sa.String(length=30), nullable=True),
        sa.Column("reason_codes", sa.Text(), nullable=False),
        sa.Column("stages", sa.Text(), nullable=False),
        sa.Column("state", sa.String(length=30), nullable=False),
        sa.Column(
            "created_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL", name="fk_feasibility_checks_created_by_user_id_users"),
            nullable=True,
        ),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column(
            "decided_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL", name="fk_feasibility_checks_decided_by_user_id_users"),
            nullable=True,
        ),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_feasibility_checks_organisation_id", "feasibility_checks", ["organisation_id"])
    op.create_index("ix_feasibility_checks_quotation_id", "feasibility_checks", ["quotation_id"])
    op.create_index("ix_feasibility_checks_customer_id", "feasibility_checks", ["customer_id"])

    op.create_table(
        "feasibility_check_lines",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "feasibility_check_id",
            sa.Integer(),
            sa.ForeignKey(
                "feasibility_checks.id",
                ondelete="CASCADE",
                name="fk_feasibility_check_lines_feasibility_check_id",
            ),
            nullable=False,
        ),
        sa.Column(
            "product_id",
            sa.Integer(),
            sa.ForeignKey("products.id", ondelete="RESTRICT", name="fk_feasibility_check_lines_product_id_products"),
            nullable=False,
        ),
        sa.Column("quantity", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column(
            "unit_of_measure_id",
            sa.Integer(),
            sa.ForeignKey(
                "units_of_measure.id",
                ondelete="RESTRICT",
                name="fk_feasibility_check_lines_unit_of_measure_id_units_of_measure",
            ),
            nullable=False,
        ),
    )
    op.create_index("ix_feasibility_check_lines_feasibility_check_id", "feasibility_check_lines", ["feasibility_check_id"])
    op.create_index("ix_feasibility_check_lines_product_id", "feasibility_check_lines", ["product_id"])
    op.create_index("ix_feasibility_check_lines_unit_of_measure_id", "feasibility_check_lines", ["unit_of_measure_id"])


def downgrade() -> None:
    op.drop_index("ix_feasibility_check_lines_unit_of_measure_id", table_name="feasibility_check_lines")
    op.drop_index("ix_feasibility_check_lines_product_id", table_name="feasibility_check_lines")
    op.drop_index("ix_feasibility_check_lines_feasibility_check_id", table_name="feasibility_check_lines")
    op.drop_table("feasibility_check_lines")
    op.drop_index("ix_feasibility_checks_customer_id", table_name="feasibility_checks")
    op.drop_index("ix_feasibility_checks_quotation_id", table_name="feasibility_checks")
    op.drop_index("ix_feasibility_checks_organisation_id", table_name="feasibility_checks")
    op.drop_table("feasibility_checks")
