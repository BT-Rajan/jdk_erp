"""Delivery Instructions (Delivery D2): one physical shipment/tranche of a
Sales Order. A Sales Order may have several; each is created manually by
warehouse staff with the `inventory:deliver` grant.

Each line keeps the Sales Order line, its ordered quantity, product and
stock unit, and this shipment's own quantity. The Delivery Scrap Allowance
applies to the Sales Order cumulatively, never per tranche: the order's
first instruction copies the Admin setting's %, every later instruction of
that order copies the same %, and the permitted total is
order quantity x (1 + % / 100) less what fulfilled instructions delivered
(delivery_instruction_service.order_position) -- derived, never stored per
tranche, so the allowance can't multiply across shipments and later
setting changes never alter an order that already has instructions.

While pending, the warehouse may change a line's shipment quantity (in
its stock unit; above the order's remaining permitted quantity only an
Admin, with a reason) and records its pallets (Delivery D3). Pallets are
handling information only -- never a unit, product, stock or conversion:
`pallet_count_default` is the system suggestion (max(1, ceil(tonnes)) for
products measured in mass, none otherwise), `pallet_count` the count used,
`pallet_count_manual` whether the warehouse set it deliberately.

Lifecycle (Delivery D4): pending -> fulfilled (final: the shipment
quantity then counts toward the Sales Order and can never change), or
pending -> not_fulfilled (reason required; counts for nothing) ->
pending again to retry the same instruction. There is no partially
fulfilled instruction -- a partial delivery is simply a smaller tranche."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import OrganisationScopedMixin, TimestampMixin

PENDING = "pending"
FULFILLED = "fulfilled"
NOT_FULFILLED = "not_fulfilled"
DELIVERY_INSTRUCTION_STATUSES = (PENDING, FULFILLED, NOT_FULFILLED)


class DeliveryInstruction(Base, TimestampMixin, OrganisationScopedMixin):
    __tablename__ = "delivery_instructions"
    __table_args__ = (
        UniqueConstraint("organisation_id", "delivery_number", name="uq_delivery_instructions_organisation_id_delivery_number"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    delivery_number: Mapped[str] = mapped_column(String(20), nullable=False)
    sales_order_id: Mapped[int] = mapped_column(ForeignKey("sales_orders.id", ondelete="RESTRICT"), nullable=False, index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=PENDING, server_default=PENDING)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    # The order's allowance %, copied from its first instruction (see above).
    scrap_allowance_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    fulfilled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    fulfilled_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    # The latest not-fulfilled attempt (cleared on retry; every attempt stays in the audit trail).
    not_fulfilled_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    not_fulfilled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    not_fulfilled_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    lines: Mapped[list["DeliveryInstructionLine"]] = relationship(
        back_populates="delivery_instruction", cascade="all, delete-orphan", order_by="DeliveryInstructionLine.id"
    )
    # Display only.
    sales_order = relationship("SalesOrder", viewonly=True, lazy="joined")
    customer = relationship("Customer", viewonly=True, lazy="joined")

    @property
    def sales_order_number(self) -> str | None:
        return self.sales_order.order_number if self.sales_order is not None else None

    @property
    def customer_name(self) -> str | None:
        return self.customer.name if self.customer is not None else None


class DeliveryInstructionLine(Base):
    __tablename__ = "delivery_instruction_lines"
    __table_args__ = (
        UniqueConstraint("delivery_instruction_id", "sales_order_line_id", name="uq_delivery_instruction_lines_instruction_line"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("pallet_count >= 1", name="pallet_count_at_least_one"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # Explicit short FK names: MySQL identifiers are limited to 64 chars.
    delivery_instruction_id: Mapped[int] = mapped_column(
        ForeignKey("delivery_instructions.id", ondelete="CASCADE", name="fk_delivery_instruction_lines_instruction_id"),
        nullable=False,
        index=True,
    )
    sales_order_line_id: Mapped[int] = mapped_column(
        ForeignKey("sales_order_lines.id", ondelete="RESTRICT", name="fk_delivery_instruction_lines_sales_order_line_id"),
        nullable=False,
        index=True,
    )
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"), nullable=False)
    unit_of_measure_id: Mapped[int] = mapped_column(
        ForeignKey("units_of_measure.id", ondelete="RESTRICT", name="fk_delivery_instruction_lines_unit_of_measure_id"),
        nullable=False,
    )
    ordered_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    # This shipment's quantity, in the stock unit.
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    # Why an Admin allowed a quantity above the remaining permitted (D3).
    quantity_override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    pallet_count_default: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pallet_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pallet_count_manual: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")

    delivery_instruction: Mapped[DeliveryInstruction] = relationship(back_populates="lines")
