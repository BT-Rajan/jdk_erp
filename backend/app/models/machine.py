from decimal import Decimal

from sqlalchemy import Boolean, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import OrganisationScopedMixin, TimestampMixin


class Machine(Base, TimestampMixin, OrganisationScopedMixin):
    """The authoritative physical production resource and its
    configured production rate (docs/modules/machines.md) -- audited
    against jdk_clean first (docs/audit/MACHINES_AUDIT.md).

    `production_line_id` is a required FK to ProductionLine -- audited
    against jdk_clean, which has no such relationship at all (its
    "machine" table already *is* what the UI calls "Production Line").
    Not unique: nothing stops two machines sharing a line later, exactly
    the room to grow the user asked for by keeping the two concepts
    genuinely separate now.

    Capacity is stored structurally as three columns -- `capacity_quantity`
    / `capacity_unit_of_measure_id` / `capacity_period_hours` -- expressing
    "capacity_quantity per capacity_period_hours," e.g. 2 tonnes per 1
    hour, never a free-text string and never hard-coded in application
    code (docs/modules/machines.md #3/#4/#14). `capacity_unit_of_measure_id`
    reuses jdk_erp's own existing UnitOfMeasure master (validated active
    and same-organisation on every write, the same treatment already
    given to Product/RawMaterial's Category/UoM FKs) rather than a
    free-text unit string.

    This is a deliberate structural departure from jdk_clean, which has
    no machine-level rate at all -- its real throughput number
    (`production_hours_per_unit`) lives on Product, entered per-product
    via batch_size/batch_production_hours, because jdk_clean's own
    Machine only tracks `capacity_hours_per_day` (an availability window,
    not a rate). The audit found no confirmed evidence that JDK's actual
    business has different real production rates per Product -- only
    that jdk_clean's schema is *capable* of a per-product rate. Per the
    user's own explicit instruction ("do not build this relationship
    unless the existing business actually has different rates by
    Product... otherwise keep the single configuration at the
    production-line/machine level"), and because jdk_erp's own Product
    model (already built) deliberately carries no rate/hours-per-unit
    field, capacity lives here, once, at the Machine level -- not a
    Machine<->Product join table. If real evidence of per-product rate
    variance surfaces later, that relationship is added then, against
    its own audit -- not built speculatively now.

    No historical snapshotting of capacity exists here either -- jdk_clean
    itself never snapshots the rate/capacity used for a past feasibility
    or production decision (a confirmed live-read-only design, not an
    oversight to fix). Whichever future Feasibility/Production-Schedule
    module reads this value is responsible for snapshotting it onto its
    own transaction row, the same discipline already documented for
    Product's price/lead-time fields and RawMaterial's reference cost."""

    __tablename__ = "machines"
    __table_args__ = (
        UniqueConstraint("organisation_id", "code", name="uq_machines_organisation_id_code"),
        UniqueConstraint("organisation_id", "name", name="uq_machines_organisation_id_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    production_line_id: Mapped[int] = mapped_column(
        ForeignKey("production_lines.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    capacity_quantity: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    capacity_unit_of_measure_id: Mapped[int] = mapped_column(
        ForeignKey("units_of_measure.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    capacity_period_hours: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1", nullable=False)
