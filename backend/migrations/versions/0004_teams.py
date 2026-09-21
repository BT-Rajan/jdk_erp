"""add teams table and users.team_id

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-21

"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Unique constraints declared inline in create_table -- SQLite has no
    # ALTER-based way to add a constraint to an existing table (batch mode
    # rebuilds the table, which create_table doesn't need to do here since
    # the table doesn't exist yet).
    op.create_table(
        "teams",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organisation_id", sa.Integer(), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("code", sa.String(length=30), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("organisation_id", "name", name="uq_teams_organisation_id_name"),
        sa.UniqueConstraint("organisation_id", "code", name="uq_teams_organisation_id_code"),
    )
    op.create_index("ix_teams_organisation_id", "teams", ["organisation_id"])

    with op.batch_alter_table("users") as batch_op:
        # SQLite batch mode rebuilds the table under the hood and requires
        # every constraint it recreates to have an explicit name.
        batch_op.add_column(
            sa.Column("team_id", sa.Integer(), sa.ForeignKey("teams.id", name="fk_users_team_id"), nullable=True)
        )
        batch_op.create_index("ix_users_team_id", ["team_id"])


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_index("ix_users_team_id")
        batch_op.drop_column("team_id")
    op.drop_table("teams")
