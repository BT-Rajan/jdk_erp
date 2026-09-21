"""session hardening: refresh_tokens.last_used_at, auth_events.actor_user_id

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-21

"""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("refresh_tokens") as batch_op:
        batch_op.add_column(sa.Column("last_used_at", sa.DateTime(), nullable=False, server_default=sa.func.now()))

    with op.batch_alter_table("auth_events") as batch_op:
        batch_op.add_column(
            sa.Column(
                "actor_user_id", sa.Integer(), sa.ForeignKey("users.id", name="fk_auth_events_actor_user_id"), nullable=True
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("auth_events") as batch_op:
        batch_op.drop_column("actor_user_id")

    with op.batch_alter_table("refresh_tokens") as batch_op:
        batch_op.drop_column("last_used_at")
