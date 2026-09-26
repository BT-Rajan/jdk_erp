"""Retire the S6 quotation-level same-day decision; add the price decision

Sales S11.1.

The same-day Admin decision now lives only on S8 feasibility records, so
quotations.same_day_override_* are dropped (every past decision remains
in audit_events as same_day_override_decided). Adds
quotations.price_decision_* for Admin's approve/reject of out-of-range or
unranged prices.

Revision ID: 0049
Revises: 0048
Create Date: 2026-09-26

"""
from alembic import op
import sqlalchemy as sa

revision = "0049"
down_revision = "0048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("quotations") as batch_op:
        batch_op.drop_constraint("fk_quotations_same_day_override_by_user_id_users", type_="foreignkey")
        batch_op.drop_column("same_day_override_at")
        batch_op.drop_column("same_day_override_by_user_id")
        batch_op.drop_column("same_day_override_reason")
        batch_op.drop_column("same_day_override_decision")
        batch_op.add_column(sa.Column("price_decision", sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column("price_decision_reason", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("price_decision_by_user_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("price_decision_at", sa.DateTime(), nullable=True))
        batch_op.create_foreign_key(
            "fk_quotations_price_decision_by_user_id_users",
            "users",
            ["price_decision_by_user_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("quotations") as batch_op:
        batch_op.drop_constraint("fk_quotations_price_decision_by_user_id_users", type_="foreignkey")
        batch_op.drop_column("price_decision_at")
        batch_op.drop_column("price_decision_by_user_id")
        batch_op.drop_column("price_decision_reason")
        batch_op.drop_column("price_decision")
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
