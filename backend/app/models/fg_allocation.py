"""Customer reservation and Finished Goods allocation (Reservation + FG
Allocation foundation).

Two different things, never interchangeable:

- SalesReservation -- the *commercial* commitment of an accepted
  quotation line, carried to its Sales Order line on conversion. Not
  physical stock: it never touches FG quantities. Keyed by quotation +
  line number (a quotation edit replaces its line rows), so it stays
  traceable to the quotation and, once converted, to the order line.

- FgAllocation -- a *claim* on physical FG already on hand, for one Sales
  Order line. Not a stock ledger: physical stock stays in
  finished_goods_inventory (its single writer untouched), and
      free FG = physical on hand - open allocations.
  One row per order line holding its current open quantity; every
  change (allocate, release, delivery consumption) is audited."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import OrganisationScopedMixin, TimestampMixin

RESERVATION_ACTIVE = "active"
RESERVATION_RELEASED = "released"
RESERVATION_FULFILLED = "fulfilled"
RESERVATION_STATUSES = (RESERVATION_ACTIVE, RESERVATION_RELEASED, RESERVATION_FULFILLED)


class SalesReservation(Base, TimestampMixin, OrganisationScopedMixin):
    __tablename__ = "sales_reservations"
    __table_args__ = (
        UniqueConstraint("quotation_id", "line_number", name="uq_sales_reservations_quotation_id_line_number"),
        UniqueConstraint("sales_order_line_id", name="uq_sales_reservations_sales_order_line_id"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    quotation_id: Mapped[int] = mapped_column(
        ForeignKey("quotations.id", ondelete="RESTRICT", name="fk_sales_reservations_quotation_id"), nullable=False, index=True
    )
    line_number: Mapped[int] = mapped_column(Integer, nullable=False)
    # Set on conversion: the same commitment, now the Sales Order's.
    sales_order_id: Mapped[int | None] = mapped_column(
        ForeignKey("sales_orders.id", ondelete="RESTRICT", name="fk_sales_reservations_sales_order_id"), nullable=True, index=True
    )
    sales_order_line_id: Mapped[int | None] = mapped_column(
        ForeignKey("sales_order_lines.id", ondelete="RESTRICT", name="fk_sales_reservations_sales_order_line_id"), nullable=True
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT", name="fk_sales_reservations_product_id"), nullable=False, index=True
    )
    unit_of_measure_id: Mapped[int] = mapped_column(
        ForeignKey("units_of_measure.id", ondelete="RESTRICT", name="fk_sales_reservations_unit_of_measure_id"), nullable=False
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=RESERVATION_ACTIVE)
    released_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    release_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class FgAllocation(Base, TimestampMixin, OrganisationScopedMixin):
    __tablename__ = "fg_allocations"
    __table_args__ = (
        UniqueConstraint("sales_order_line_id", name="uq_fg_allocations_sales_order_line_id"),
        CheckConstraint("quantity >= 0", name="quantity_not_negative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    sales_order_id: Mapped[int] = mapped_column(
        ForeignKey("sales_orders.id", ondelete="RESTRICT", name="fk_fg_allocations_sales_order_id"), nullable=False, index=True
    )
    sales_order_line_id: Mapped[int] = mapped_column(
        ForeignKey("sales_order_lines.id", ondelete="RESTRICT", name="fk_fg_allocations_sales_order_line_id"), nullable=False
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT", name="fk_fg_allocations_product_id"), nullable=False, index=True
    )
    # The product's stock unit (the order line's unit, checked at hand-off).
    unit_of_measure_id: Mapped[int] = mapped_column(
        ForeignKey("units_of_measure.id", ondelete="RESTRICT", name="fk_fg_allocations_unit_of_measure_id"), nullable=False
    )
    # Current open claim; 0 once fully delivered or released.
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False, default=0)
