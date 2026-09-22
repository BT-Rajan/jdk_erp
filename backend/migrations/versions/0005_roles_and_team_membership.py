"""add users.role, replace users.team_id with many-to-many user_teams

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-21

"""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        # The FK constraint must be dropped before the index it depends on --
        # MySQL refuses to drop an index that's still backing a foreign key
        # (error 1553), which native (non-rebuild) batch mode on MySQL hits
        # since drop_index/drop_column run as separate ALTER statements.
        batch_op.drop_constraint("fk_users_team_id", type_="foreignkey")
        batch_op.drop_index("ix_users_team_id")
        batch_op.drop_column("team_id")
        # "team_member" (least-privilege) backfills any pre-existing rows;
        # the ORM model sets it explicitly for every new row going
        # forward, same pattern as migration 0002's organisation fields.
        batch_op.add_column(sa.Column("role", sa.String(length=20), nullable=False, server_default="team_member"))

    op.create_table(
        "user_teams",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("team_id", sa.Integer(), sa.ForeignKey("teams.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("user_id", "team_id", name="uq_user_teams_user_id_team_id"),
    )
    op.create_index("ix_user_teams_user_id", "user_teams", ["user_id"])
    op.create_index("ix_user_teams_team_id", "user_teams", ["team_id"])


def downgrade() -> None:
    op.drop_table("user_teams")

    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("role")
        batch_op.add_column(
            sa.Column("team_id", sa.Integer(), sa.ForeignKey("teams.id", name="fk_users_team_id"), nullable=True)
        )
        batch_op.create_index("ix_users_team_id", ["team_id"])
