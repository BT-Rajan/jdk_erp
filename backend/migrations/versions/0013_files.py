"""add files table (docs/modules/file_storage.md #2)

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-22

"""
from alembic import op
import sqlalchemy as sa

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "files",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organisation_id",
            sa.Integer(),
            sa.ForeignKey("organisations.id", ondelete="RESTRICT", name="fk_files_organisation_id_organisations"),
            nullable=False,
        ),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("storage_key", sa.String(length=64), nullable=False),
        sa.Column("mime_type", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("entity_type", sa.String(length=30), nullable=True),
        sa.Column("entity_id", sa.Integer(), nullable=True),
        sa.Column(
            "uploaded_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL", name="fk_files_uploaded_by_user_id_users"),
            nullable=True,
        ),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="ready"),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("storage_key", name="uq_files_storage_key"),
    )
    op.create_index("ix_files_organisation_id", "files", ["organisation_id"])
    op.create_index("ix_files_uploaded_by_user_id", "files", ["uploaded_by_user_id"])
    op.create_index("ix_files_entity_type_entity_id", "files", ["entity_type", "entity_id"])


def downgrade() -> None:
    op.drop_table("files")
