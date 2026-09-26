from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import OrganisationScopedMixin, TimestampMixin

# Lifecycle (S14.2): an order is handed off to fulfilment automatically
# the moment it is created, and stays handed_off until Admin cancels it.
# Fulfilment (stock, production, QC, delivery) reads the order; no
# fulfilment states live here. Orders created before S14.2 were `open`;
# migration 0052 marked them handed off (source `migration`).
HANDED_OFF = "handed_off"
CANCELLED = "cancelled"
# Delivery statuses (Delivery D2): recognised so delivery eligibility can
# name them; nothing sets them yet -- later Delivery passes will.
PARTIALLY_DELIVERED = "partially_delivered"
COMPLETED = "completed"
SALES_ORDER_STATUSES = (HANDED_OFF, PARTIALLY_DELIVERED, COMPLETED, CANCELLED)

# How an order reached hand-off: `automatic` on creation (S14.2), or
# `migration` for orders that existed before it.
HANDOFF_AUTOMATIC = "automatic"
HANDOFF_MIGRATION = "migration"


class SalesOrder(Base, TimestampMixin, OrganisationScopedMixin):
    """A Sales Order converted by the owning salesman from one accepted
    quotation (S13.1). It holds the quotation's commercial snapshot; the
    quotation itself becomes `converted` and is locked. Visibility comes
    from `customer_id` (S2), like every Sales record.

    `order_number` is `YY6NNNN` (document_numbering), assigned once and
    never changed; orders are never deleted, only cancelled. Amounts are
    server-calculated. It is the fulfilment side's source of truth; only
    Admin may change a handed-off order (date, quantities, prices -- never
    the customer, products or units) or cancel it, always with a reason
    (audited)."""

    __tablename__ = "sales_orders"
    __table_args__ = (
        UniqueConstraint("organisation_id", "order_number", name="uq_sales_orders_organisation_id_order_number"),
        UniqueConstraint("quotation_id", name="uq_sales_orders_quotation_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    order_number: Mapped[str] = mapped_column(String(20), nullable=False)
    quotation_id: Mapped[int] = mapped_column(ForeignKey("quotations.id", ondelete="RESTRICT"), nullable=False)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True)
    order_date: Mapped[date] = mapped_column(Date, nullable=False)
    requested_delivery_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    subtotal_amount: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=HANDED_OFF, server_default=HANDED_OFF)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cancelled_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The hand-off (S14.2). handed_off_by_user_id is the authenticated user
    # whose order creation triggered it; handoff_source says it was the
    # automatic transition, not a separate manual action.
    handed_off_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    handed_off_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    handoff_source: Mapped[str | None] = mapped_column(String(20), nullable=True)

    lines: Mapped[list["SalesOrderLine"]] = relationship(
        back_populates="sales_order", cascade="all, delete-orphan", order_by="SalesOrderLine.line_number"
    )
    # Display only.
    customer = relationship("Customer", viewonly=True, lazy="joined")
    quotation = relationship("Quotation", viewonly=True, lazy="joined")

    @property
    def customer_name(self) -> str | None:
        return self.customer.name if self.customer is not None else None

    @property
    def quotation_number(self) -> str | None:
        return self.quotation.quotation_number if self.quotation is not None else None


class SalesOrderLine(Base):
    """One ordered product: quantity in the product's own unit, the agreed
    unit price and the server-calculated amount -- copied from the
    quotation line at conversion, re-priced only by an Admin edit."""

    __tablename__ = "sales_order_lines"
    __table_args__ = (
        UniqueConstraint("sales_order_id", "line_number", name="uq_sales_order_lines_sales_order_id_line_number"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    sales_order_id: Mapped[int] = mapped_column(ForeignKey("sales_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    line_number: Mapped[int] = mapped_column(nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    unit_of_measure_id: Mapped[int] = mapped_column(
        ForeignKey("units_of_measure.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    line_amount: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)

    sales_order: Mapped[SalesOrder] = relationship(back_populates="lines")
