"""AI assistant API key (organisations.ai_api_key_encrypted)

The provider API key for the JDK Assistant, Fernet-encrypted at rest.

Revision ID: 0054
Revises: 0053
Create Date: 2026-09-26

"""
from alembic import op
import sqlalchemy as sa

revision = "0054"
down_revision = "0053"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("organisations") as batch:
        batch.add_column(sa.Column("ai_api_key_encrypted", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("organisations") as batch:
        batch.drop_column("ai_api_key_encrypted")
