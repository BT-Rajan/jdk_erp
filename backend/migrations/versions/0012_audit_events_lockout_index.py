"""composite index for the login-lockout query, drop the now-redundant
standalone username_attempted index (docs/modules/database_transaction_integrity.md #3)

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-22

"""
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_audit_events_username_attempted", table_name="audit_events")
    op.create_index(
        "ix_audit_events_username_attempted_action_created_at",
        "audit_events",
        ["username_attempted", "action", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_audit_events_username_attempted_action_created_at", table_name="audit_events")
    op.create_index("ix_audit_events_username_attempted", "audit_events", ["username_attempted"])
