"""Quotation acceptance, rejection and validity (Sales S12)

quotations.valid_until -- last day a draft can be accepted (quotation date
+ 7 calendar days; renewal restarts it). Existing rows are backfilled from
their own quotation_date, computed in Python so it is portable.
quotations.accepted_* / rejected_* / rejection_reason -- who decided and
when. `status` already exists (String(20)); it now also takes
`accepted` / `rejected`.

Revision ID: 0050
Revises: 0049
Create Date: 2026-09-26

"""
from datetime import timedelta

from alembic import op
import sqlalchemy as sa

revision = "0050"
down_revision = "0049"
branch_labels = None
depends_on = None

VALIDITY_DAYS = 7


def upgrade() -> None:
    with op.batch_alter_table("quotations") as batch_op:
        batch_op.add_column(sa.Column("valid_until", sa.Date(), nullable=True))
        batch_op.add_column(sa.Column("accepted_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("accepted_by_user_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("rejected_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("rejected_by_user_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("rejection_reason", sa.Text(), nullable=True))
        batch_op.create_foreign_key(
            "fk_quotations_accepted_by_user_id_users", "users", ["accepted_by_user_id"], ["id"], ondelete="SET NULL"
        )
        batch_op.create_foreign_key(
            "fk_quotations_rejected_by_user_id_users", "users", ["rejected_by_user_id"], ["id"], ondelete="SET NULL"
        )

    quotations = sa.table(
        "quotations", sa.column("id", sa.Integer()), sa.column("quotation_date", sa.Date()), sa.column("valid_until", sa.Date())
    )
    connection = op.get_bind()
    for row in connection.execute(sa.select(quotations.c.id, quotations.c.quotation_date)).fetchall():
        connection.execute(
            quotations.update()
            .where(quotations.c.id == row.id)
            .values(valid_until=row.quotation_date + timedelta(days=VALIDITY_DAYS))
        )

    with op.batch_alter_table("quotations") as batch_op:
        batch_op.alter_column("valid_until", existing_type=sa.Date(), nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("quotations") as batch_op:
        batch_op.drop_constraint("fk_quotations_rejected_by_user_id_users", type_="foreignkey")
        batch_op.drop_constraint("fk_quotations_accepted_by_user_id_users", type_="foreignkey")
        batch_op.drop_column("rejection_reason")
        batch_op.drop_column("rejected_by_user_id")
        batch_op.drop_column("rejected_at")
        batch_op.drop_column("accepted_by_user_id")
        batch_op.drop_column("accepted_at")
        batch_op.drop_column("valid_until")
