from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import OrganisationScopedMixin, TimestampMixin

# Lifecycle (Sales S8). `calculated` and `not_servable` are final results
# of the calculation itself; `admin_override_required` waits for Admin,
# who moves it to `approved` or `rejected` (and may change that decision
# later -- each decision is audited).
CALCULATED = "calculated"
ADMIN_OVERRIDE_REQUIRED = "admin_override_required"
APPROVED = "approved"
REJECTED = "rejected"
NOT_SERVABLE = "not_servable"
FEASIBILITY_STATES = (CALCULATED, ADMIN_OVERRIDE_REQUIRED, APPROVED, REJECTED, NOT_SERVABLE)
DECIDABLE_STATES = (ADMIN_OVERRIDE_REQUIRED, APPROVED, REJECTED)


class FeasibilityCheck(Base, TimestampMixin, OrganisationScopedMixin):
    """One feasibility calculation for a quotation, kept forever as it was
    calculated (Sales S8). A re-check is a new row; nothing here is
    rewritten except the Admin decision fields and `state` moving between
    the decidable states. The inputs the calculation used are snapshotted
    (requested date here, quantities in FeasibilityCheckLine), so a later
    change to the quotation can be detected rather than silently reusing
    this result (see feasibility_record_service.is_current).

    `result` / `failed_stage` / `reason_codes` / `stages` are the
    calculation's own output and are never changed by an Admin decision."""

    __tablename__ = "feasibility_checks"

    id: Mapped[int] = mapped_column(primary_key=True)
    quotation_id: Mapped[int] = mapped_column(ForeignKey("quotations.id", ondelete="RESTRICT"), nullable=False, index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True)
    requested_delivery_date: Mapped[date] = mapped_column(Date, nullable=False)
    delivery_window: Mapped[str] = mapped_column(String(30), nullable=False)
    # Which calculation produced this row, e.g. "same_day_fg/v1".
    calculation_basis: Mapped[str] = mapped_column(String(40), nullable=False)
    calculated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    result: Mapped[str] = mapped_column(String(30), nullable=False)
    failed_stage: Mapped[str | None] = mapped_column(String(30), nullable=True)
    reason_codes: Mapped[str] = mapped_column(Text, nullable=False)  # JSON list
    stages: Mapped[str] = mapped_column(Text, nullable=False)  # JSON list of stage results
    state: Mapped[str] = mapped_column(String(30), nullable=False)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    decision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    lines: Mapped[list["FeasibilityCheckLine"]] = relationship(
        back_populates="feasibility_check", cascade="all, delete-orphan", order_by="FeasibilityCheckLine.id"
    )


class FeasibilityCheckLine(Base):
    """The requested quantity the calculation used, snapshotted."""

    __tablename__ = "feasibility_check_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    feasibility_check_id: Mapped[int] = mapped_column(
        ForeignKey("feasibility_checks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    unit_of_measure_id: Mapped[int] = mapped_column(
        ForeignKey("units_of_measure.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    feasibility_check: Mapped[FeasibilityCheck] = relationship(back_populates="lines")
