"""Production Requirement follows allocation

A requirement's quantity is now its current uncovered demand (ordered -
delivered - allocated). The terminal "demand met" state is `satisfied`
(replacing `fulfilled`, with its timestamp column), and a CHECK keeps the
status to the four lifecycle values.

Revision ID: 0061
Revises: 0060
Create Date: 2026-09-26

"""
from alembic import op
import sqlalchemy as sa

revision = "0061"
down_revision = "0060"
branch_labels = None
depends_on = None

_CHECK = "ck_production_requirements_status_valid"


def upgrade() -> None:
    op.execute("UPDATE production_requirements SET status = 'satisfied' WHERE status = 'fulfilled'")
    with op.batch_alter_table("production_requirements") as batch:
        batch.alter_column("fulfilled_at", new_column_name="satisfied_at", existing_type=sa.DateTime(), existing_nullable=True)
        batch.create_check_constraint(_CHECK, "status IN ('open', 'bom_required', 'satisfied', 'cancelled')")


def downgrade() -> None:
    with op.batch_alter_table("production_requirements") as batch:
        batch.drop_constraint(_CHECK, type_="check")
        batch.alter_column("satisfied_at", new_column_name="fulfilled_at", existing_type=sa.DateTime(), existing_nullable=True)
    op.execute("UPDATE production_requirements SET status = 'fulfilled' WHERE status = 'satisfied'")
