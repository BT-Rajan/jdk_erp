"""Production Order (P5): production work formally issued to the factory --
an executable instruction derived from a scheduled Production Plan. Not a
Sales Order, a Production Requirement, an MRP plan, a schedule or an
inventory movement; it needs no Sales Order.

One order covers (part of) one schedule entry, and through it one
Production Plan and that plan's source (a Production Requirement ->
Sales Order line, or independent production). A plan split across
several days gets one order per entry; several orders may share an
entry as long as together they stay within its quantity.

Lifecycle: `draft` (editable, not executable) -> `issued` (formally
issued; product, quantity, unit, BOM snapshot, machine and date are then
fixed) -> `in_progress` (execution started) -> `partially_completed`
(some of the quantity produced) -> `completed` (all of it produced;
final). Cancelling (reason, kept) is possible from draft, or from issued /
in progress only while nothing has been produced. The produced quantity
is never stored here: it is the sum of the order's posted executions
(production_execution.py).

At issue the production basis is snapshotted onto the order: the plan's
BOM snapshot (base quantity; each component's quantity per base and its
raw material's own unit) and each component's requirement for this
order's quantity -- never re-resolved from the current BOM."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import OrganisationScopedMixin, TimestampMixin

ORDER_DRAFT = "draft"
ORDER_ISSUED = "issued"
# Execution states (P6 -- Production Execution).
ORDER_IN_PROGRESS = "in_progress"
ORDER_PARTIALLY_COMPLETED = "partially_completed"
ORDER_COMPLETED = "completed"
ORDER_CANCELLED = "cancelled"
ORDER_STATUSES = (ORDER_DRAFT, ORDER_ISSUED, ORDER_IN_PROGRESS, ORDER_PARTIALLY_COMPLETED, ORDER_COMPLETED, ORDER_CANCELLED)
# Every order that still holds its schedule quantity (all but cancelled).
ORDER_ACTIVE = (ORDER_DRAFT, ORDER_ISSUED, ORDER_IN_PROGRESS, ORDER_PARTIALLY_COMPLETED, ORDER_COMPLETED)
# Production may be recorded against these.
ORDER_EXECUTABLE = (ORDER_ISSUED, ORDER_IN_PROGRESS, ORDER_PARTIALLY_COMPLETED)


class ProductionOrder(Base, TimestampMixin, OrganisationScopedMixin):
    __tablename__ = "production_orders"
    __table_args__ = (
        UniqueConstraint("organisation_id", "order_number", name="uq_production_orders_organisation_id_order_number"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint(
            "status IN ('draft', 'issued', 'in_progress', 'partially_completed', 'completed', 'cancelled')", name="status_valid"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    order_number: Mapped[str] = mapped_column(String(20), nullable=False)
    production_plan_id: Mapped[int] = mapped_column(
        ForeignKey("production_plans.id", ondelete="RESTRICT", name="fk_production_orders_plan_id"), nullable=False, index=True
    )
    production_schedule_entry_id: Mapped[int] = mapped_column(
        ForeignKey("production_schedule_entries.id", ondelete="RESTRICT", name="fk_production_orders_schedule_entry_id"),
        nullable=False,
        index=True,
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT", name="fk_production_orders_product_id"), nullable=False, index=True
    )
    # The product's production (stock) unit.
    unit_of_measure_id: Mapped[int] = mapped_column(
        ForeignKey("units_of_measure.id", ondelete="RESTRICT", name="fk_production_orders_unit_of_measure_id"), nullable=False
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    machine_id: Mapped[int] = mapped_column(
        ForeignKey("machines.id", ondelete="RESTRICT", name="fk_production_orders_machine_id"), nullable=False
    )
    scheduled_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=ORDER_DRAFT)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # BOM basis, snapshotted at issue (null while draft).
    bom_id: Mapped[int | None] = mapped_column(ForeignKey("boms.id", ondelete="SET NULL", name="fk_production_orders_bom_id"), nullable=True)
    bom_base_quantity: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL", name="fk_production_orders_created_by_user_id"), nullable=True
    )
    issued_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    issued_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL", name="fk_production_orders_issued_by_user_id"), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    started_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL", name="fk_production_orders_started_by_user_id"), nullable=True
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    components: Mapped[list["ProductionOrderComponent"]] = relationship(
        cascade="all, delete-orphan", order_by="ProductionOrderComponent.id"
    )
    plan = relationship("ProductionPlan", viewonly=True, lazy="joined")
    schedule_entry = relationship("ProductionScheduleEntry", viewonly=True, lazy="joined")


class ProductionOrderComponent(Base):
    """One BOM component as issued: quantity per BOM base quantity, the raw
    material's own unit, and the requirement for the order's quantity."""

    __tablename__ = "production_order_components"
    __table_args__ = (
        UniqueConstraint("production_order_id", "raw_material_id", name="uq_production_order_components_order_material"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("required_quantity > 0", name="required_quantity_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    production_order_id: Mapped[int] = mapped_column(
        ForeignKey("production_orders.id", ondelete="CASCADE", name="fk_production_order_components_order_id"), nullable=False, index=True
    )
    raw_material_id: Mapped[int] = mapped_column(
        ForeignKey("raw_materials.id", ondelete="RESTRICT", name="fk_production_order_components_raw_material_id"), nullable=False
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    unit_of_measure_id: Mapped[int] = mapped_column(
        ForeignKey("units_of_measure.id", ondelete="RESTRICT", name="fk_production_order_components_unit_of_measure_id"), nullable=False
    )
    required_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
