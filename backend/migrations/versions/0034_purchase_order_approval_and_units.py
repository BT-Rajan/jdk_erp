"""Purchase Order approval flow, currency, delivery instructions,
history stamps, supplier-quotation reference, and per-line purchase unit /
required-by date / remarks (docs/modules/purchase_orders.md)

Existing data is carried forward:
- statuses: issued -> approved, supplier_confirmed -> sent,
  fully_received -> received;
- approved_at/by from the current revision, sent_at/by from the old
  supplier-confirmation stamp;
- currency from the organisation;
- every existing line in its material's own unit, factor 1.

Revision ID: 0034
Revises: 0033
Create Date: 2026-09-24

"""
from alembic import op
import sqlalchemy as sa

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None

_USER_STAMPS = ("created_by_user_id", "approved_by_user_id", "sent_by_user_id", "cancelled_by_user_id")


def upgrade() -> None:
    with op.batch_alter_table("purchase_orders") as batch_op:
        batch_op.add_column(sa.Column("rfq_response_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("currency", sa.String(length=3), nullable=False, server_default="KWD"))
        batch_op.add_column(sa.Column("delivery_instructions", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("approved_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("sent_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("cancelled_at", sa.DateTime(), nullable=True))
        for column in _USER_STAMPS:
            batch_op.add_column(sa.Column(column, sa.Integer(), nullable=True))

    with op.batch_alter_table("purchase_orders") as batch_op:
        batch_op.create_foreign_key(
            "fk_purchase_orders_rfq_response_id_rfq_responses", "rfq_responses", ["rfq_response_id"], ["id"], ondelete="SET NULL"
        )
        for column in _USER_STAMPS:
            batch_op.create_foreign_key(f"fk_purchase_orders_{column}_users", "users", [column], ["id"], ondelete="SET NULL")

    op.execute(
        "UPDATE purchase_orders SET currency = "
        "(SELECT o.currency FROM organisations o WHERE o.id = purchase_orders.organisation_id)"
    )
    op.execute(
        """
        UPDATE purchase_orders
        SET approved_at = (
                SELECT r.issued_at FROM purchase_order_revisions r
                WHERE r.purchase_order_id = purchase_orders.id AND r.revision_number = purchase_orders.revision_number
            ),
            approved_by_user_id = (
                SELECT r.issued_by_user_id FROM purchase_order_revisions r
                WHERE r.purchase_order_id = purchase_orders.id AND r.revision_number = purchase_orders.revision_number
            )
        WHERE status IN ('issued', 'supplier_confirmed', 'partially_received', 'fully_received')
        """
    )
    op.execute(
        """
        UPDATE purchase_orders
        SET sent_at = supplier_confirmed_at, sent_by_user_id = supplier_confirmed_by_user_id
        WHERE status IN ('supplier_confirmed', 'partially_received', 'fully_received')
        """
    )
    op.execute("UPDATE purchase_orders SET status = 'approved' WHERE status = 'issued'")
    op.execute("UPDATE purchase_orders SET status = 'sent' WHERE status = 'supplier_confirmed'")
    op.execute("UPDATE purchase_orders SET status = 'received' WHERE status = 'fully_received'")

    with op.batch_alter_table("purchase_order_lines") as batch_op:
        batch_op.add_column(sa.Column("unit_of_measure_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("conversion_factor", sa.Numeric(precision=18, scale=6), nullable=False, server_default="1"))
        batch_op.add_column(sa.Column("required_by_date", sa.Date(), nullable=True))
        batch_op.add_column(sa.Column("remarks", sa.Text(), nullable=True))
    op.execute(
        "UPDATE purchase_order_lines SET unit_of_measure_id = "
        "(SELECT rm.unit_of_measure_id FROM raw_materials rm WHERE rm.id = purchase_order_lines.raw_material_id)"
    )
    with op.batch_alter_table("purchase_order_lines") as batch_op:
        batch_op.alter_column("unit_of_measure_id", existing_type=sa.Integer(), nullable=False)
        batch_op.create_foreign_key(
            "fk_purchase_order_lines_unit_of_measure_id_units_of_measure",
            "units_of_measure",
            ["unit_of_measure_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_index("ix_purchase_order_lines_unit_of_measure_id", ["unit_of_measure_id"])

    with op.batch_alter_table("purchase_order_revision_lines") as batch_op:
        batch_op.add_column(sa.Column("unit_of_measure_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("required_by_date", sa.Date(), nullable=True))
        batch_op.add_column(sa.Column("remarks", sa.Text(), nullable=True))
    op.execute(
        "UPDATE purchase_order_revision_lines SET unit_of_measure_id = "
        "(SELECT rm.unit_of_measure_id FROM raw_materials rm WHERE rm.id = purchase_order_revision_lines.raw_material_id)"
    )
    with op.batch_alter_table("purchase_order_revision_lines") as batch_op:
        # Shortened name -- the full one exceeds MySQL's 64-character limit.
        batch_op.create_foreign_key(
            "fk_po_revision_lines_unit_of_measure_id", "units_of_measure", ["unit_of_measure_id"], ["id"], ondelete="RESTRICT"
        )


def downgrade() -> None:
    with op.batch_alter_table("purchase_order_revision_lines") as batch_op:
        batch_op.drop_constraint("fk_po_revision_lines_unit_of_measure_id", type_="foreignkey")
        batch_op.drop_column("remarks")
        batch_op.drop_column("required_by_date")
        batch_op.drop_column("unit_of_measure_id")

    with op.batch_alter_table("purchase_order_lines") as batch_op:
        batch_op.drop_constraint("fk_purchase_order_lines_unit_of_measure_id_units_of_measure", type_="foreignkey")
        batch_op.drop_index("ix_purchase_order_lines_unit_of_measure_id")
        batch_op.drop_column("remarks")
        batch_op.drop_column("required_by_date")
        batch_op.drop_column("conversion_factor")
        batch_op.drop_column("unit_of_measure_id")

    op.execute("UPDATE purchase_orders SET status = 'draft' WHERE status = 'pending_approval'")
    op.execute("UPDATE purchase_orders SET status = 'issued' WHERE status = 'approved'")
    op.execute("UPDATE purchase_orders SET status = 'supplier_confirmed' WHERE status = 'sent'")
    op.execute("UPDATE purchase_orders SET status = 'fully_received' WHERE status = 'received'")

    with op.batch_alter_table("purchase_orders") as batch_op:
        batch_op.drop_constraint("fk_purchase_orders_rfq_response_id_rfq_responses", type_="foreignkey")
        for column in _USER_STAMPS:
            batch_op.drop_constraint(f"fk_purchase_orders_{column}_users", type_="foreignkey")
        for column in ("rfq_response_id", "currency", "delivery_instructions", "approved_at", "sent_at", "cancelled_at", *_USER_STAMPS):
            batch_op.drop_column(column)
