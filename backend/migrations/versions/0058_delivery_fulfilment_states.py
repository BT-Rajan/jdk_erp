"""Delivery Instruction fulfilment states (Delivery D4)

delivery_instructions gains who/when fulfilled, and the latest
not-fulfilled attempt (reason, who, when). Status now also takes
`fulfilled` and `not_fulfilled` (String(20), no enum change needed).

Revision ID: 0058
Revises: 0057
Create Date: 2026-09-26

"""
from alembic import op
import sqlalchemy as sa

revision = "0058"
down_revision = "0057"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("delivery_instructions") as batch:
        batch.add_column(sa.Column("fulfilled_at", sa.DateTime(), nullable=True))
        batch.add_column(
            sa.Column(
                "fulfilled_by_user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="SET NULL", name="fk_delivery_instructions_fulfilled_by_user_id_users"),
                nullable=True,
            )
        )
        batch.add_column(sa.Column("not_fulfilled_reason", sa.Text(), nullable=True))
        batch.add_column(sa.Column("not_fulfilled_at", sa.DateTime(), nullable=True))
        batch.add_column(
            sa.Column(
                "not_fulfilled_by_user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="SET NULL", name="fk_delivery_instructions_not_fulfilled_by_user_id_users"),
                nullable=True,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("delivery_instructions") as batch:
        batch.drop_constraint("fk_delivery_instructions_not_fulfilled_by_user_id_users", type_="foreignkey")
        batch.drop_column("not_fulfilled_by_user_id")
        batch.drop_column("not_fulfilled_at")
        batch.drop_column("not_fulfilled_reason")
        batch.drop_constraint("fk_delivery_instructions_fulfilled_by_user_id_users", type_="foreignkey")
        batch.drop_column("fulfilled_by_user_id")
        batch.drop_column("fulfilled_at")
