"""add RFQ tables (docs/modules/rfq.md)

Revision ID: 0028
Revises: 0027
Create Date: 2026-09-23

"""
from alembic import op
import sqlalchemy as sa

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # rfqs.selected_response_id and rfq_responses.rfq_id form a circular
    # FK pair -- selected_response_id is created here as a plain nullable
    # column with no constraint yet, and given its FK once rfq_responses
    # exists (below), the standard way to break a two-table FK cycle.
    op.create_table(
        "rfqs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "organisation_id",
            sa.Integer(),
            sa.ForeignKey("organisations.id", ondelete="RESTRICT", name="fk_rfqs_organisation_id_organisations"),
            nullable=False,
        ),
        sa.Column("rfq_number", sa.String(length=10), nullable=False),
        sa.Column(
            "supplier_id",
            sa.Integer(),
            sa.ForeignKey("suppliers.id", ondelete="RESTRICT", name="fk_rfqs_supplier_id_suppliers"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("rfq_date", sa.Date(), nullable=False),
        sa.Column("required_delivery_date", sa.Date(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("cancel_reason", sa.Text(), nullable=True),
        sa.Column(
            "decided_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL", name="fk_rfqs_decided_by_user_id_users"),
            nullable=True,
        ),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("selected_response_id", sa.Integer(), nullable=True),
        sa.Column(
            "purchase_order_id",
            sa.Integer(),
            sa.ForeignKey("purchase_orders.id", ondelete="SET NULL", name="fk_rfqs_purchase_order_id_purchase_orders"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("organisation_id", "rfq_number", name="uq_rfqs_organisation_id_rfq_number"),
    )
    op.create_index("ix_rfqs_organisation_id", "rfqs", ["organisation_id"])
    op.create_index("ix_rfqs_supplier_id", "rfqs", ["supplier_id"])
    op.create_index("ix_rfqs_purchase_order_id", "rfqs", ["purchase_order_id"])

    op.create_table(
        "rfq_lines",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "rfq_id",
            sa.Integer(),
            sa.ForeignKey("rfqs.id", ondelete="CASCADE", name="fk_rfq_lines_rfq_id_rfqs"),
            nullable=False,
        ),
        sa.Column(
            "raw_material_id",
            sa.Integer(),
            sa.ForeignKey("raw_materials.id", ondelete="RESTRICT", name="fk_rfq_lines_raw_material_id_raw_materials"),
            nullable=False,
        ),
        sa.Column("quantity", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_rfq_lines_rfq_id", "rfq_lines", ["rfq_id"])
    op.create_index("ix_rfq_lines_raw_material_id", "rfq_lines", ["raw_material_id"])

    op.create_table(
        "rfq_responses",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "organisation_id",
            sa.Integer(),
            sa.ForeignKey("organisations.id", ondelete="RESTRICT", name="fk_rfq_responses_organisation_id_organisations"),
            nullable=False,
        ),
        sa.Column(
            "rfq_id",
            sa.Integer(),
            sa.ForeignKey("rfqs.id", ondelete="CASCADE", name="fk_rfq_responses_rfq_id_rfqs"),
            nullable=False,
        ),
        sa.Column("response_received_at", sa.DateTime(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL", name="fk_rfq_responses_created_by_user_id_users"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_rfq_responses_organisation_id", "rfq_responses", ["organisation_id"])
    op.create_index("ix_rfq_responses_rfq_id", "rfq_responses", ["rfq_id"])

    with op.batch_alter_table("rfqs") as batch_op:
        batch_op.create_foreign_key(
            "fk_rfqs_selected_response_id_rfq_responses",
            "rfq_responses",
            ["selected_response_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index("ix_rfqs_selected_response_id", "rfqs", ["selected_response_id"])


def downgrade() -> None:
    with op.batch_alter_table("rfqs") as batch_op:
        batch_op.drop_index("ix_rfqs_selected_response_id")
        batch_op.drop_constraint("fk_rfqs_selected_response_id_rfq_responses", type_="foreignkey")

    op.drop_table("rfq_responses")
    op.drop_table("rfq_lines")
    op.drop_table("rfqs")
