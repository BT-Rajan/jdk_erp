"""supplier payments against a purchase order
(docs/modules/purchase_orders.md, Revision 3)

Revision ID: 0030
Revises: 0029
Create Date: 2026-09-23

"""
from alembic import op
import sqlalchemy as sa

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "purchase_order_payments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "organisation_id",
            sa.Integer(),
            sa.ForeignKey(
                "organisations.id", ondelete="RESTRICT", name="fk_purchase_order_payments_organisation_id_organisations"
            ),
            nullable=False,
        ),
        sa.Column("payment_number", sa.String(length=20), nullable=False),
        sa.Column(
            "purchase_order_id",
            sa.Integer(),
            sa.ForeignKey(
                "purchase_orders.id", ondelete="RESTRICT", name="fk_purchase_order_payments_purchase_order_id_purchase_orders"
            ),
            nullable=False,
        ),
        sa.Column("payment_date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column("payment_method", sa.String(length=60), nullable=True),
        sa.Column("reference_number", sa.String(length=120), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=10), nullable=False, server_default="recorded"),
        sa.Column("cancelled_at", sa.DateTime(), nullable=True),
        sa.Column(
            "cancelled_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL", name="fk_purchase_order_payments_cancelled_by_user_id_users"),
            nullable=True,
        ),
        sa.Column("cancellation_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL", name="fk_purchase_order_payments_created_by_user_id_users"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "organisation_id", "payment_number", name="uq_purchase_order_payments_organisation_id_payment_number"
        ),
    )
    op.create_index("ix_purchase_order_payments_organisation_id", "purchase_order_payments", ["organisation_id"])
    op.create_index("ix_purchase_order_payments_purchase_order_id", "purchase_order_payments", ["purchase_order_id"])


def downgrade() -> None:
    op.drop_table("purchase_order_payments")
