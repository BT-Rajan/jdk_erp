"""add organisations.email_domain (docs/modules/common_validation.md #1)

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-22

"""
from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("organisations") as batch_op:
        # Nullable: an organisation with no configured domain has no
        # company-email-domain restriction at all
        # (app.core.validation.validate_company_email_domain).
        batch_op.add_column(sa.Column("email_domain", sa.String(length=255), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("organisations") as batch_op:
        batch_op.drop_column("email_domain")
