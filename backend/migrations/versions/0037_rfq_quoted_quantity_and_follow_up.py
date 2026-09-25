"""RFQ gap fixes: quoted quantity per response line, supplier follow-up
notes (docs/modules/rfq.md gap-fix pass).

- rfq_response_lines.quantity -- the quantity a supplier actually quoted,
  when it differs from the RFQ line's requested quantity. Nullable:
  null means "the requested quantity", never forced.
- rfq_invitation_follow_ups -- a simple, append-only follow-up note
  history per invited supplier.

Revision ID: 0037
Revises: 0036
Create Date: 2026-09-25

"""
from alembic import op
import sqlalchemy as sa

revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("rfq_response_lines") as batch_op:
        batch_op.add_column(sa.Column("quantity", sa.Numeric(precision=14, scale=4), nullable=True))

    op.create_table(
        "rfq_invitation_follow_ups",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "invitation_id",
            sa.Integer(),
            sa.ForeignKey(
                "rfq_supplier_invitations.id", ondelete="CASCADE", name="fk_rfq_invitation_follow_ups_invitation_id"
            ),
            nullable=False,
        ),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column(
            "created_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL", name="fk_rfq_invitation_follow_ups_created_by_user_id"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_rfq_invitation_follow_ups_invitation_id", "rfq_invitation_follow_ups", ["invitation_id"]
    )


def downgrade() -> None:
    # Dropping a table drops its indexes; dropping an FK-backing index
    # first fails on MySQL.
    op.drop_table("rfq_invitation_follow_ups")

    with op.batch_alter_table("rfq_response_lines") as batch_op:
        batch_op.drop_column("quantity")
