"""add email_accounts table (Communication module, email channel)

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-22

"""
from alembic import op
import sqlalchemy as sa

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "email_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organisation_id",
            sa.Integer(),
            sa.ForeignKey(
                "organisations.id", ondelete="RESTRICT", name="fk_email_accounts_organisation_id_organisations"
            ),
            nullable=False,
        ),
        sa.Column("provider", sa.String(length=20), nullable=False, server_default="gmail"),
        sa.Column("email_address", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("display_name", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("username", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("password_encrypted", sa.Text(), nullable=True),
        sa.Column("incoming_protocol", sa.String(length=10), nullable=False, server_default="imap"),
        sa.Column("imap_host", sa.String(length=255), nullable=False, server_default="imap.gmail.com"),
        sa.Column("imap_port", sa.Integer(), nullable=False, server_default="993"),
        sa.Column("imap_use_ssl", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("pop3_host", sa.String(length=255), nullable=False, server_default="pop.gmail.com"),
        sa.Column("pop3_port", sa.Integer(), nullable=False, server_default="995"),
        sa.Column("pop3_use_ssl", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("smtp_host", sa.String(length=255), nullable=False, server_default="smtp.gmail.com"),
        sa.Column("smtp_port", sa.Integer(), nullable=False, server_default="587"),
        sa.Column("smtp_use_tls", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("last_tested_at", sa.DateTime(), nullable=True),
        sa.Column("last_test_ok", sa.Boolean(), nullable=True),
        sa.Column("last_test_error", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("organisation_id", name="uq_email_accounts_organisation_id"),
    )
    op.create_index("ix_email_accounts_organisation_id", "email_accounts", ["organisation_id"])


def downgrade() -> None:
    op.drop_table("email_accounts")
