"""fix schema drift: audit_events.action was never widened to match the
model when 0008 renamed it from event_type (docs/modules/database_transaction_integrity.md
#1/#4) -- caught by `alembic check`, which found the live schema
(VARCHAR(20), from 0001's original event_type) disagreeing with
app/models/audit_event.py's action: String(30). Harmless on SQLite (no
length enforcement) but would truncate/reject on MySQL, this project's
one supported production database.

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-22

"""
from alembic import op
import sqlalchemy as sa

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("audit_events") as batch_op:
        batch_op.alter_column("action", existing_type=sa.String(length=20), type_=sa.String(length=30))


def downgrade() -> None:
    with op.batch_alter_table("audit_events") as batch_op:
        batch_op.alter_column("action", existing_type=sa.String(length=30), type_=sa.String(length=20))
