"""RFQ revision number, line units and per-line required-by date,
invitation email stamp, and admin document templates (letterhead) for the
RFQ PDF (docs/modules/rfq.md)

Existing RFQ lines are backfilled with their raw material's own unit;
already-issued RFQs start at revision 1, drafts at 0.

Revision ID: 0033
Revises: 0032
Create Date: 2026-09-24

"""
from alembic import op
import sqlalchemy as sa

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("rfqs") as batch_op:
        batch_op.add_column(sa.Column("revision_number", sa.Integer(), nullable=False, server_default="0"))
    op.execute("UPDATE rfqs SET revision_number = 1 WHERE status <> 'draft'")

    with op.batch_alter_table("rfq_lines") as batch_op:
        batch_op.add_column(sa.Column("unit_of_measure_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("required_by_date", sa.Date(), nullable=True))

    op.execute(
        """
        UPDATE rfq_lines
        SET unit_of_measure_id = (
            SELECT rm.unit_of_measure_id FROM raw_materials rm WHERE rm.id = rfq_lines.raw_material_id
        )
        """
    )

    with op.batch_alter_table("rfq_lines") as batch_op:
        batch_op.alter_column("unit_of_measure_id", existing_type=sa.Integer(), nullable=False)
        batch_op.create_foreign_key(
            "fk_rfq_lines_unit_of_measure_id_units_of_measure",
            "units_of_measure",
            ["unit_of_measure_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_index("ix_rfq_lines_unit_of_measure_id", ["unit_of_measure_id"])

    with op.batch_alter_table("rfq_supplier_invitations") as batch_op:
        batch_op.add_column(sa.Column("last_emailed_at", sa.DateTime(), nullable=True))

    op.create_table(
        "document_templates",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "organisation_id",
            sa.Integer(),
            sa.ForeignKey("organisations.id", ondelete="RESTRICT", name="fk_document_templates_organisation_id_organisations"),
            nullable=False,
        ),
        sa.Column("document_type", sa.String(length=20), nullable=False),
        sa.Column(
            "letterhead_file_id",
            sa.Integer(),
            sa.ForeignKey("files.id", ondelete="SET NULL", name="fk_document_templates_letterhead_file_id_files"),
            nullable=True,
        ),
        sa.Column("margin_top_mm", sa.Integer(), nullable=False, server_default="40"),
        sa.Column("margin_bottom_mm", sa.Integer(), nullable=False, server_default="25"),
        sa.Column("intro_text", sa.Text(), nullable=True),
        sa.Column("terms_text", sa.Text(), nullable=True),
        sa.Column("signature_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("organisation_id", "document_type", name="uq_document_templates_org_id_document_type"),
    )
    op.create_index("ix_document_templates_organisation_id", "document_templates", ["organisation_id"])


def downgrade() -> None:
    op.drop_index("ix_document_templates_organisation_id", table_name="document_templates")
    op.drop_table("document_templates")

    with op.batch_alter_table("rfq_supplier_invitations") as batch_op:
        batch_op.drop_column("last_emailed_at")

    with op.batch_alter_table("rfq_lines") as batch_op:
        batch_op.drop_index("ix_rfq_lines_unit_of_measure_id")
        batch_op.drop_constraint("fk_rfq_lines_unit_of_measure_id_units_of_measure", type_="foreignkey")
        batch_op.drop_column("required_by_date")
        batch_op.drop_column("unit_of_measure_id")

    with op.batch_alter_table("rfqs") as batch_op:
        batch_op.drop_column("revision_number")
