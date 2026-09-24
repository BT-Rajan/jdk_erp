"""Purchase Order receipt/payment reconciliation, supplier follow-up
history, automatic closing (docs/modules/purchase_orders.md Revision 6)

- purchase_orders.status widened to 30 characters for the new statuses
  (reconciliation_required, payment_reconciliation, closed);
- purchase_orders.amount_adjustment, purchase_order_lines.cancelled_quantity,
  purchase_order_payments.is_final, purchase_order_receipt_lines.remarks;
- purchase_order_reconciliations and purchase_order_communications tables.

Existing statuses are left as they are; each PO's status is re-derived
the next time a receipt, payment or reconciliation touches it.

Revision ID: 0035
Revises: 0034
Create Date: 2026-09-24

"""
from alembic import op
import sqlalchemy as sa

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("purchase_orders") as batch_op:
        batch_op.alter_column("status", existing_type=sa.String(length=20), type_=sa.String(length=30), existing_nullable=False)
        batch_op.add_column(sa.Column("amount_adjustment", sa.Numeric(precision=14, scale=4), nullable=False, server_default="0"))

    with op.batch_alter_table("purchase_order_lines") as batch_op:
        batch_op.add_column(sa.Column("cancelled_quantity", sa.Numeric(precision=14, scale=4), nullable=False, server_default="0"))

    with op.batch_alter_table("purchase_order_payments") as batch_op:
        batch_op.add_column(sa.Column("is_final", sa.Boolean(), nullable=False, server_default="0"))

    with op.batch_alter_table("purchase_order_receipt_lines") as batch_op:
        batch_op.add_column(sa.Column("remarks", sa.Text(), nullable=True))

    op.create_table(
        "purchase_order_reconciliations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "purchase_order_id",
            sa.Integer(),
            sa.ForeignKey("purchase_orders.id", ondelete="CASCADE", name="fk_po_reconciliations_purchase_order_id"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False, server_default="open"),
        sa.Column("discrepancy", sa.Text(), nullable=False),
        sa.Column("resolution", sa.String(length=30), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column(
            "resolved_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL", name="fk_po_reconciliations_resolved_by_user_id"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_purchase_order_reconciliations_purchase_order_id", "purchase_order_reconciliations", ["purchase_order_id"])

    op.create_table(
        "purchase_order_communications",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "purchase_order_id",
            sa.Integer(),
            sa.ForeignKey("purchase_orders.id", ondelete="CASCADE", name="fk_po_communications_purchase_order_id"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("recipient", sa.String(length=255), nullable=True),
        sa.Column("subject", sa.String(length=255), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "sent_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL", name="fk_po_communications_sent_by_user_id"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_purchase_order_communications_purchase_order_id", "purchase_order_communications", ["purchase_order_id"])


def downgrade() -> None:
    # Dropping a table drops its indexes; dropping an FK-backing index
    # first fails on MySQL.
    op.drop_table("purchase_order_communications")
    op.drop_table("purchase_order_reconciliations")

    # Map the new derived statuses back to their nearest earlier ones.
    op.execute("UPDATE purchase_orders SET status = 'partially_received' WHERE status = 'reconciliation_required'")
    op.execute("UPDATE purchase_orders SET status = 'received' WHERE status IN ('payment_reconciliation', 'closed')")

    with op.batch_alter_table("purchase_order_receipt_lines") as batch_op:
        batch_op.drop_column("remarks")
    with op.batch_alter_table("purchase_order_payments") as batch_op:
        batch_op.drop_column("is_final")
    with op.batch_alter_table("purchase_order_lines") as batch_op:
        batch_op.drop_column("cancelled_quantity")
    with op.batch_alter_table("purchase_orders") as batch_op:
        batch_op.drop_column("amount_adjustment")
        batch_op.alter_column("status", existing_type=sa.String(length=30), type_=sa.String(length=20), existing_nullable=False)
