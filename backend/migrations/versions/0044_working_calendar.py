"""Working calendar: organisation same-day cut-off and holidays

Sales S1 -- the shared, organisation-level working calendar the Sales
delivery-window classifier reads (app/services/working_calendar_service.py).
The Sunday-Thursday working week is a fixed business rule in code; only
the Admin-configurable parts are stored:

organisations.same_day_cutoff_time -- Kuwait wall-clock cut-off for
same-day delivery, 14:00 by default (also the backfill for existing rows).

organisation_holidays -- one row per organisation per non-working date.

Revision ID: 0044
Revises: 0043
Create Date: 2026-09-26

"""
from alembic import op
import sqlalchemy as sa

revision = "0044"
down_revision = "0043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("organisations") as batch_op:
        batch_op.add_column(sa.Column("same_day_cutoff_time", sa.Time(), nullable=False, server_default="14:00:00"))

    op.create_table(
        "organisation_holidays",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "organisation_id",
            sa.Integer(),
            sa.ForeignKey(
                "organisations.id", ondelete="RESTRICT", name="fk_organisation_holidays_organisation_id_organisations"
            ),
            nullable=False,
        ),
        sa.Column("holiday_date", sa.Date(), nullable=False),
        sa.Column("description", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "organisation_id", "holiday_date", name="uq_organisation_holidays_organisation_id_holiday_date"
        ),
    )
    op.create_index("ix_organisation_holidays_organisation_id", "organisation_holidays", ["organisation_id"])


def downgrade() -> None:
    op.drop_index("ix_organisation_holidays_organisation_id", table_name="organisation_holidays")
    op.drop_table("organisation_holidays")
    with op.batch_alter_table("organisations") as batch_op:
        batch_op.drop_column("same_day_cutoff_time")
