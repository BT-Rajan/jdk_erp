"""Reservation + FG Allocation foundation

sales_reservations: the commercial commitment of an accepted quotation
line, carried to its Sales Order line. fg_allocations: one row per Sales
Order line holding its current open claim on physical Finished Goods.
Neither touches finished_goods_inventory or its movements; nothing
existing is rewritten or backfilled.

Revision ID: 0060
Revises: 0059
Create Date: 2026-09-26

"""
from alembic import op
import sqlalchemy as sa

revision = "0060"
down_revision = "0059"
branch_labels = None
depends_on = None


def _fk(target: str, name: str, ondelete: str) -> sa.ForeignKey:
    return sa.ForeignKey(target, ondelete=ondelete, name=name)


def upgrade() -> None:
    op.create_table(
        "sales_reservations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organisation_id", sa.Integer(), _fk("organisations.id", "fk_sales_reservations_organisation_id_organisations", "RESTRICT"), nullable=False),
        sa.Column("quotation_id", sa.Integer(), _fk("quotations.id", "fk_sales_reservations_quotation_id", "RESTRICT"), nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("sales_order_id", sa.Integer(), _fk("sales_orders.id", "fk_sales_reservations_sales_order_id", "RESTRICT"), nullable=True),
        sa.Column("sales_order_line_id", sa.Integer(), _fk("sales_order_lines.id", "fk_sales_reservations_sales_order_line_id", "RESTRICT"), nullable=True),
        sa.Column("product_id", sa.Integer(), _fk("products.id", "fk_sales_reservations_product_id", "RESTRICT"), nullable=False),
        sa.Column("unit_of_measure_id", sa.Integer(), _fk("units_of_measure.id", "fk_sales_reservations_unit_of_measure_id", "RESTRICT"), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("released_at", sa.DateTime(), nullable=True),
        sa.Column("release_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("quotation_id", "line_number", name="uq_sales_reservations_quotation_id_line_number"),
        sa.UniqueConstraint("sales_order_line_id", name="uq_sales_reservations_sales_order_line_id"),
        sa.CheckConstraint("quantity > 0", name="ck_sales_reservations_quantity_positive"),
    )
    op.create_index("ix_sales_reservations_organisation_id", "sales_reservations", ["organisation_id"])
    op.create_index("ix_sales_reservations_quotation_id", "sales_reservations", ["quotation_id"])
    op.create_index("ix_sales_reservations_sales_order_id", "sales_reservations", ["sales_order_id"])
    op.create_index("ix_sales_reservations_product_id", "sales_reservations", ["product_id"])

    op.create_table(
        "fg_allocations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organisation_id", sa.Integer(), _fk("organisations.id", "fk_fg_allocations_organisation_id_organisations", "RESTRICT"), nullable=False),
        sa.Column("sales_order_id", sa.Integer(), _fk("sales_orders.id", "fk_fg_allocations_sales_order_id", "RESTRICT"), nullable=False),
        sa.Column("sales_order_line_id", sa.Integer(), _fk("sales_order_lines.id", "fk_fg_allocations_sales_order_line_id", "RESTRICT"), nullable=False),
        sa.Column("product_id", sa.Integer(), _fk("products.id", "fk_fg_allocations_product_id", "RESTRICT"), nullable=False),
        sa.Column("unit_of_measure_id", sa.Integer(), _fk("units_of_measure.id", "fk_fg_allocations_unit_of_measure_id", "RESTRICT"), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("sales_order_line_id", name="uq_fg_allocations_sales_order_line_id"),
        sa.CheckConstraint("quantity >= 0", name="ck_fg_allocations_quantity_not_negative"),
    )
    op.create_index("ix_fg_allocations_organisation_id", "fg_allocations", ["organisation_id"])
    op.create_index("ix_fg_allocations_sales_order_id", "fg_allocations", ["sales_order_id"])
    op.create_index("ix_fg_allocations_product_id", "fg_allocations", ["product_id"])


def downgrade() -> None:
    op.drop_table("fg_allocations")
    op.drop_table("sales_reservations")
