"""RFQ: remove the department (team) reference -- an RFQ no longer
depends on a department (docs/modules/rfq.md #2)

Revision ID: 0036
Revises: 0035
Create Date: 2026-09-24

"""
from alembic import op
import sqlalchemy as sa

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("rfqs") as batch_op:
        batch_op.drop_index("ix_rfqs_team_id")
        batch_op.drop_constraint("fk_rfqs_team_id_teams", type_="foreignkey")
        batch_op.drop_column("team_id")


def downgrade() -> None:
    with op.batch_alter_table("rfqs") as batch_op:
        batch_op.add_column(
            sa.Column(
                "team_id",
                sa.Integer(),
                sa.ForeignKey("teams.id", ondelete="SET NULL", name="fk_rfqs_team_id_teams"),
                nullable=True,
            )
        )
        batch_op.create_index("ix_rfqs_team_id", ["team_id"])
