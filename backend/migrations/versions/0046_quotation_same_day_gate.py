"""Quotation requested delivery date and same-day FG override decision

Sales S6. All columns nullable; existing quotations get no requested date
and no decision.

Revision ID: 0046
Revises: 0045
Create Date: 2026-09-26

"""
from alembic import op
import sqlalchemy as sa

revision = "0046"
down_revision = "0045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("quotations") as batch_op:
        batch_op.add_column(sa.Column("requested_delivery_date", sa.Date(), nullable=True))
        batch_op.add_column(sa.Column("same_day_override_decision", sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column("same_day_override_reason", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("same_day_override_by_user_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("same_day_override_at", sa.DateTime(), nullable=True))
        batch_op.create_foreign_key(
            "fk_quotations_same_day_override_by_user_id_users",
            "users",
            ["same_day_override_by_user_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("quotations") as batch_op:
        batch_op.drop_constraint("fk_quotations_same_day_override_by_user_id_users", type_="foreignkey")
        batch_op.drop_column("same_day_override_at")
        batch_op.drop_column("same_day_override_by_user_id")
        batch_op.drop_column("same_day_override_reason")
        batch_op.drop_column("same_day_override_decision")
        batch_op.drop_column("requested_delivery_date")
