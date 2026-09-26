"""Production Schedule (P4)

production_schedule_entries: a quantity of an accepted Production Plan on a
working day, on a machine, in sequence (scheduled / cancelled).
organisations.production_hours_per_day: the Admin-set production hours of
a working day, turning a machine's capacity per N hours into a daily
capacity (NULL = not configured). No inventory, no Production Order.

Revision ID: 0063
Revises: 0062
Create Date: 2026-09-26

"""
from alembic import op
import sqlalchemy as sa

revision = "0063"
down_revision = "0062"
branch_labels = None
depends_on = None


def _fk(target: str, name: str, ondelete: str) -> sa.ForeignKey:
    return sa.ForeignKey(target, ondelete=ondelete, name=name)


def upgrade() -> None:
    with op.batch_alter_table("organisations") as batch:
        batch.add_column(sa.Column("production_hours_per_day", sa.Numeric(precision=4, scale=2), nullable=True))
    op.create_table(
        "production_schedule_entries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organisation_id", sa.Integer(), _fk("organisations.id", "fk_production_schedule_entries_organisation_id_organisations", "RESTRICT"), nullable=False),
        sa.Column("production_plan_id", sa.Integer(), _fk("production_plans.id", "fk_production_schedule_entries_plan_id", "RESTRICT"), nullable=False),
        sa.Column("machine_id", sa.Integer(), _fk("machines.id", "fk_production_schedule_entries_machine_id", "RESTRICT"), nullable=False),
        sa.Column("scheduled_date", sa.Date(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("daily_capacity_snapshot", sa.Numeric(precision=14, scale=4), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), _fk("users.id", "fk_production_schedule_entries_created_by_user_id", "SET NULL"), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(), nullable=True),
        sa.Column("cancellation_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_production_schedule_entries_quantity_positive"),
        sa.CheckConstraint("sequence >= 1", name="ck_production_schedule_entries_sequence_positive"),
        sa.CheckConstraint("status IN ('scheduled', 'cancelled')", name="ck_production_schedule_entries_status_valid"),
    )
    op.create_index("ix_production_schedule_entries_organisation_id", "production_schedule_entries", ["organisation_id"])
    op.create_index("ix_production_schedule_entries_production_plan_id", "production_schedule_entries", ["production_plan_id"])
    op.create_index("ix_production_schedule_entries_machine_id", "production_schedule_entries", ["machine_id"])
    op.create_index("ix_production_schedule_entries_scheduled_date", "production_schedule_entries", ["scheduled_date"])


def downgrade() -> None:
    op.drop_table("production_schedule_entries")
    with op.batch_alter_table("organisations") as batch:
        batch.drop_column("production_hours_per_day")
