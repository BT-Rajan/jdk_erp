from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import OrganisationScopedMixin, TimestampMixin

# Sales S4 is the data foundation only: a quotation is created as a draft
# and nothing moves it anywhere else yet. Acceptance, rejection, expiry,
# revision and conversion are later passes -- their states are added then,
# not guessed now.
DRAFT = "draft"
QUOTATION_STATUSES = (DRAFT,)

# Admin's decision on a same-day Finished Goods shortage (Sales S6).
OVERRIDE_APPROVED = "approved"
OVERRIDE_REJECTED = "rejected"
SAME_DAY_OVERRIDE_DECISIONS = (OVERRIDE_APPROVED, OVERRIDE_REJECTED)


class Quotation(Base, TimestampMixin, OrganisationScopedMixin):
    """A customer quotation header. Ownership and visibility come only
    from `customer_id` (Sales record -> Customer -> assigned owner, see
    app/services/customer_scope.py) -- there is deliberately no Sales
    owner column of its own. `created_by_user_id` is authorship history,
    never access.

    `quotation_number` is `YY4NNNN` (app/services/document_numbering.py),
    assigned once on insert and never written again: no update path
    touches it, and quotations are never hard-deleted, so it is never
    reused. Amounts are server-calculated from the lines and rounded to
    `currency`'s minor unit (app/core/currency.py)."""

    __tablename__ = "quotations"
    __table_args__ = (
        UniqueConstraint("organisation_id", "quotation_number", name="uq_quotations_organisation_id_quotation_number"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    quotation_number: Mapped[str] = mapped_column(String(20), nullable=False)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    quotation_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=DRAFT, server_default=DRAFT)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    subtotal_amount: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    # True when any line's price needs Admin approval (see QuotationLine).
    # Derived from the lines at creation; the approval workflow itself is
    # a later pass.
    price_approval_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # The customer's requested delivery date, as asked -- never moved by
    # the system. Its delivery window is always classified live
    # (app/services/working_calendar_service.py), never stored.
    requested_delivery_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Admin's current decision on a same-day FG shortage
    # (app/services/same_day_fg_service.py). Admin may change it; every
    # decision is kept in the audit trail, so only the latest lives here.
    same_day_override_decision: Mapped[str | None] = mapped_column(String(20), nullable=True)
    same_day_override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    same_day_override_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    same_day_override_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    lines: Mapped[list["QuotationLine"]] = relationship(
        back_populates="quotation", cascade="all, delete-orphan", order_by="QuotationLine.line_number"
    )
    # Display only: names shown on lists/detail, always read live.
    customer = relationship("Customer", viewonly=True, lazy="joined")
    created_by = relationship("User", foreign_keys=[created_by_user_id], viewonly=True, lazy="joined")

    @property
    def customer_name(self) -> str | None:
        return self.customer.name if self.customer is not None else None

    @property
    def created_by_name(self) -> str | None:
        return self.created_by.full_name if self.created_by is not None else None


class QuotationLine(Base):
    """One quoted product. Product and unit are live references, but the
    commercial facts that must not drift when the Product changes are
    snapshotted here: the unit the quantity is expressed in, the price,
    and the permitted price range the price was checked against."""

    __tablename__ = "quotation_lines"
    __table_args__ = (
        UniqueConstraint("quotation_id", "line_number", name="uq_quotation_lines_quotation_id_line_number"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    quotation_id: Mapped[int] = mapped_column(ForeignKey("quotations.id", ondelete="CASCADE"), nullable=False, index=True)
    line_number: Mapped[int] = mapped_column(nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    # Always the product's own unit at quotation time -- no conversion.
    unit_of_measure_id: Mapped[int] = mapped_column(
        ForeignKey("units_of_measure.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    line_amount: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    # The product's permitted range when this line was priced (NULL = no
    # range was set, which itself requires approval).
    min_selling_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    max_selling_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    price_approval_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    quotation: Mapped[Quotation] = relationship(back_populates="lines")
