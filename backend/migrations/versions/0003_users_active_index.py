"""add composite (organisation_id, is_active) index on users

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-21

"""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_users_organisation_id_is_active", "users", ["organisation_id", "is_active"])


def downgrade() -> None:
    op.drop_index("ix_users_organisation_id_is_active", table_name="users")
