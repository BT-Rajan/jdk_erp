"""purchase order commercial-document workflow: rfq linkage, supplier
confirmation, and an immutable issue/revision history
(docs/modules/purchase_orders.md, Revision 2)

Revision ID: 0029
Revises: 0028
Create Date: 2026-09-23

"""
from alembic import op
import sqlalchemy as sa

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("purchase_orders") as batch_op:
        batch_op.add_column(sa.Column("rfq_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("revision_number", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("supplier_reference", sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column("payment_terms", sa.String(length=200), nullable=True))
        batch_op.add_column(sa.Column("supplier_confirmed_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("supplier_confirmed_by_user_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("supplier_confirmation_note", sa.Text(), nullable=True))
        batch_op.create_foreign_key(
            "fk_purchase_orders_rfq_id_rfqs", "rfqs", ["rfq_id"], ["id"], ondelete="SET NULL"
        )
        batch_op.create_foreign_key(
            "fk_purchase_orders_supplier_confirmed_by_user_id_users",
            "users",
            ["supplier_confirmed_by_user_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index("ix_purchase_orders_rfq_id", "purchase_orders", ["rfq_id"])

    # Renamed status value: existing rows (dev-only, no production data
    # yet) carrying the old "confirmed" meaning ("ready to receive") now
    # map onto "supplier_confirmed" -- the closest equivalent in the new
    # model, since the old status conflated "issued" and "accepted" into
    # one value (docs/modules/purchase_orders.md #23).
    op.execute("UPDATE purchase_orders SET status = 'supplier_confirmed' WHERE status = 'confirmed'")

    # One immutable row per draft -> issued transition
    # (docs/modules/purchase_orders.md #24) -- never updated after
    # creation.
    op.create_table(
        "purchase_order_revisions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "purchase_order_id",
            sa.Integer(),
            sa.ForeignKey(
                "purchase_orders.id", ondelete="CASCADE", name="fk_purchase_order_revisions_purchase_order_id_purchase_orders"
            ),
            nullable=False,
        ),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("order_date", sa.Date(), nullable=False),
        sa.Column("expected_delivery_date", sa.Date(), nullable=True),
        sa.Column("supplier_reference", sa.String(length=100), nullable=True),
        sa.Column("payment_terms", sa.String(length=200), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("total_amount", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column("issued_at", sa.DateTime(), nullable=False),
        sa.Column(
            "issued_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL", name="fk_purchase_order_revisions_issued_by_user_id_users"),
            nullable=True,
        ),
        sa.UniqueConstraint(
            "purchase_order_id", "revision_number", name="uq_purchase_order_revisions_purchase_order_id_revision_number"
        ),
    )
    op.create_index("ix_purchase_order_revisions_purchase_order_id", "purchase_order_revisions", ["purchase_order_id"])

    # A frozen copy of each PurchaseOrderLine at issue time -- never a
    # live reference to the current (possibly since-edited)
    # purchase_order_lines row.
    op.create_table(
        "purchase_order_revision_lines",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "revision_id",
            sa.Integer(),
            sa.ForeignKey(
                "purchase_order_revisions.id",
                ondelete="CASCADE",
                # Shortened from fk_purchase_order_revision_lines_revision_id_purchase_order_revisions
                # (69 chars) -- MySQL rejects any identifier over 64 characters.
                name="fk_purchase_order_revision_lines_revision_id_po_revisions",
            ),
            nullable=False,
        ),
        sa.Column(
            "raw_material_id",
            sa.Integer(),
            sa.ForeignKey(
                "raw_materials.id",
                ondelete="RESTRICT",
                name="fk_purchase_order_revision_lines_raw_material_id_raw_materials",
            ),
            nullable=False,
        ),
        sa.Column("quantity", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column("line_total", sa.Numeric(precision=14, scale=4), nullable=False),
    )
    op.create_index("ix_purchase_order_revision_lines_revision_id", "purchase_order_revision_lines", ["revision_id"])
    op.create_index(
        "ix_purchase_order_revision_lines_raw_material_id", "purchase_order_revision_lines", ["raw_material_id"]
    )


def downgrade() -> None:
    op.drop_table("purchase_order_revision_lines")
    op.drop_table("purchase_order_revisions")

    op.execute("UPDATE purchase_orders SET status = 'confirmed' WHERE status = 'supplier_confirmed'")

    with op.batch_alter_table("purchase_orders") as batch_op:
        batch_op.drop_index("ix_purchase_orders_rfq_id")
        batch_op.drop_constraint("fk_purchase_orders_supplier_confirmed_by_user_id_users", type_="foreignkey")
        batch_op.drop_constraint("fk_purchase_orders_rfq_id_rfqs", type_="foreignkey")
        batch_op.drop_column("supplier_confirmation_note")
        batch_op.drop_column("supplier_confirmed_by_user_id")
        batch_op.drop_column("supplier_confirmed_at")
        batch_op.drop_column("payment_terms")
        batch_op.drop_column("supplier_reference")
        batch_op.drop_column("revision_number")
        batch_op.drop_column("rfq_id")
