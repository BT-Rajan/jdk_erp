"""RFQ gap fix: split sourcing -- let a Purchase Order line record which
RFQ line it was converted from, so several suppliers' POs against the
same RFQ line can be added back up to show how much has been sourced
and how much remains (docs/modules/rfq.md gap-fix pass).

purchase_order_lines.rfq_line_id -- nullable: null for a PO raised
directly with no RFQ.

Revision ID: 0039
Revises: 0038
Create Date: 2026-09-25

"""
from alembic import op
import sqlalchemy as sa

revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("purchase_order_lines") as batch_op:
        batch_op.add_column(sa.Column("rfq_line_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_purchase_order_lines_rfq_line_id_rfq_lines",
            "rfq_lines",
            ["rfq_line_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index("ix_purchase_order_lines_rfq_line_id", "purchase_order_lines", ["rfq_line_id"])


def downgrade() -> None:
    op.drop_index("ix_purchase_order_lines_rfq_line_id", table_name="purchase_order_lines")
    with op.batch_alter_table("purchase_order_lines") as batch_op:
        batch_op.drop_constraint("fk_purchase_order_lines_rfq_line_id_rfq_lines", type_="foreignkey")
        batch_op.drop_column("rfq_line_id")
