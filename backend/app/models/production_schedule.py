"""Production Schedule (P4): *when* an accepted Production Plan will be
produced -- an operational commitment, not production and not proof that
anything was made.

One entry = a quantity of one planned Production Plan on one working day
on one machine (and so its production line), in sequence. A plan may be
split across several entries/days; the active entries never total more
than the plan's quantity. Product and unit are the plan's -- never copied
as editable values here. The plan's required-by date (demand) is never
moved; an entry after it is flagged late.

Status: `scheduled` or `cancelled` (reason, kept). Moves and quantity
changes are audited old -> new (module `production`); cancelling an entry
never cancels its plan, and cancelling a plan cancels its entries.

`daily_capacity_snapshot` records the machine's daily capacity (in the
machine's capacity unit) used when the entry was last scheduled, as the
Machine model asks a schedule to do; the live day view reads current
capacity."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import OrganisationScopedMixin, TimestampMixin

SCHEDULED = "scheduled"
SCHEDULE_CANCELLED = "cancelled"
SCHEDULE_STATUSES = (SCHEDULED, SCHEDULE_CANCELLED)


class ProductionScheduleEntry(Base, TimestampMixin, OrganisationScopedMixin):
    __tablename__ = "production_schedule_entries"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("sequence >= 1", name="sequence_positive"),
        CheckConstraint("status IN ('scheduled', 'cancelled')", name="status_valid"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    production_plan_id: Mapped[int] = mapped_column(
        ForeignKey("production_plans.id", ondelete="RESTRICT", name="fk_production_schedule_entries_plan_id"), nullable=False, index=True
    )
    machine_id: Mapped[int] = mapped_column(
        ForeignKey("machines.id", ondelete="RESTRICT", name="fk_production_schedule_entries_machine_id"), nullable=False, index=True
    )
    scheduled_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    # In the plan's (product's) unit.
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=SCHEDULED)
    daily_capacity_snapshot: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL", name="fk_production_schedule_entries_created_by_user_id"), nullable=True
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    plan = relationship("ProductionPlan", viewonly=True, lazy="joined")
