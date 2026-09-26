"""Sales Order fulfilment hand-off (Sales S14.2)

customers -- payment_arrangement (before_delivery / after_delivery /
payment_plan) and payment_plan_details, set by Admin.
sales_orders -- handed_off_at, handed_off_by_user_id, handoff_source; the
status default becomes `handed_off`. Every existing `open` order is marked
handed off (source `migration`, at its creation time, by its creator).

Revision ID: 0052
Revises: 0051
Create Date: 2026-09-26

"""
from alembic import op
import sqlalchemy as sa

revision = "0052"
down_revision = "0051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("customers") as batch:
        batch.add_column(sa.Column("payment_arrangement", sa.String(length=20), nullable=True))
        batch.add_column(sa.Column("payment_plan_details", sa.Text(), nullable=True))

    with op.batch_alter_table("sales_orders") as batch:
        batch.add_column(sa.Column("handed_off_at", sa.DateTime(), nullable=True))
        batch.add_column(
            sa.Column(
                "handed_off_by_user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="SET NULL", name="fk_sales_orders_handed_off_by_user_id_users"),
                nullable=True,
            )
        )
        batch.add_column(sa.Column("handoff_source", sa.String(length=20), nullable=True))
        batch.alter_column("status", existing_type=sa.String(length=20), existing_nullable=False, server_default="handed_off")

    op.execute(
        "UPDATE sales_orders SET status = 'handed_off', handed_off_at = created_at, "
        "handed_off_by_user_id = created_by_user_id, handoff_source = 'migration' WHERE status = 'open'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE sales_orders SET status = 'open' WHERE status = 'handed_off'"
    )
    with op.batch_alter_table("sales_orders") as batch:
        batch.alter_column("status", existing_type=sa.String(length=20), existing_nullable=False, server_default="open")
        batch.drop_column("handoff_source")
        batch.drop_constraint("fk_sales_orders_handed_off_by_user_id_users", type_="foreignkey")
        batch.drop_column("handed_off_by_user_id")
        batch.drop_column("handed_off_at")

    with op.batch_alter_table("customers") as batch:
        batch.drop_column("payment_plan_details")
        batch.drop_column("payment_arrangement")
