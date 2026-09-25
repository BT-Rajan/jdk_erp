"""RFQ gap fix: record the UoM a supplier actually quoted in, when it
differs from the RFQ line's own requested unit (docs/modules/rfq.md
gap-fix pass).

rfq_response_lines.unit_of_measure_id -- nullable: null means "the RFQ
line's own requested unit". Validated active and convertible to the
material's own unit at capture time, the same discipline
RfqLine.unit_of_measure_id already applies.

Revision ID: 0038
Revises: 0037
Create Date: 2026-09-25

"""
from alembic import op
import sqlalchemy as sa

revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("rfq_response_lines") as batch_op:
        batch_op.add_column(sa.Column("unit_of_measure_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_rfq_response_lines_unit_of_measure_id_units_of_measure",
            "units_of_measure",
            ["unit_of_measure_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    op.create_index(
        "ix_rfq_response_lines_unit_of_measure_id", "rfq_response_lines", ["unit_of_measure_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_rfq_response_lines_unit_of_measure_id", table_name="rfq_response_lines")
    with op.batch_alter_table("rfq_response_lines") as batch_op:
        batch_op.drop_constraint("fk_rfq_response_lines_unit_of_measure_id_units_of_measure", type_="foreignkey")
        batch_op.drop_column("unit_of_measure_id")
