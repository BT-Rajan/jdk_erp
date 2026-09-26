"""Fulfilment result per Sales Order line, and the Production Requirement
for any shortfall (Sales S15.2, per the S15.1 decisions).

Both are created automatically when a Sales Order is handed off, one line
at a time: available Finished Goods (Inventory's on-hand figure) cover
the line first; only the remainder becomes production demand. A line
fully covered from stock gets a fulfilment result and no Production
Requirement.

Nothing here is commercial: customer, prices, ordered quantity and the
requested delivery date stay on the Sales Order, which remains the source
of truth -- the required-by date is read from it, never copied. Nothing
here reserves, allocates, moves or issues stock, schedules, plans or
executes production.

Lifecycle (Production P1). A requirement is a demand/reference record --
the shortfall of one order line -- never an instruction to manufacture
exactly that quantity:
- `bom_required` -> `open`: the product's active BOM is snapshotted once
  one exists (production_requirement_service.snapshot_bom);
- `open`/`bom_required` -> `fulfilled`: the order line has been delivered
  in full, so the demand is satisfied;
- `open`/`bom_required` -> `cancelled`: the Sales Order was cancelled, or
  an Admin quantity change left the line with no shortfall (such a
  requirement returns to its previous state if a later change creates a
  shortfall again). Never deleted; every transition is audited."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import OrganisationScopedMixin, TimestampMixin

# Fulfilment result of a line at hand-off.
FROM_STOCK = "from_stock"
PRODUCTION_REQUIRED = "production_required"
FULFILMENT_RESULTS = (FROM_STOCK, PRODUCTION_REQUIRED)

# Production Requirement state. `open` carries the snapshot of the
# product's active BOM taken when it was created; `bom_required` means the
# product had no active BOM then (S15.2 decision: the demand is still
# recorded, flagged).
REQUIREMENT_OPEN = "open"
REQUIREMENT_BOM_REQUIRED = "bom_required"
REQUIREMENT_FULFILLED = "fulfilled"
REQUIREMENT_CANCELLED = "cancelled"
REQUIREMENT_STATUSES = (REQUIREMENT_OPEN, REQUIREMENT_BOM_REQUIRED, REQUIREMENT_FULFILLED, REQUIREMENT_CANCELLED)
# Still demand: may change, be resolved or be cancelled.
REQUIREMENT_ACTIVE = (REQUIREMENT_OPEN, REQUIREMENT_BOM_REQUIRED)


class SalesOrderLineFulfilment(Base, OrganisationScopedMixin):
    """How one Sales Order line is to be fulfilled, as assessed once at
    hand-off: the quantity covered by Finished Goods on hand and the
    quantity left for production (together, the ordered quantity then).
    Both in the line's unit, which is the product's own stock unit. One
    per line; never recalculated."""

    __tablename__ = "sales_order_line_fulfilments"
    __table_args__ = (
        UniqueConstraint("sales_order_line_id", name="uq_sales_order_line_fulfilments_sales_order_line_id"),
        CheckConstraint("fg_available_quantity >= 0", name="fg_available"),
        CheckConstraint("fg_covered_quantity >= 0", name="fg_covered"),
        CheckConstraint("production_quantity >= 0", name="production"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    sales_order_id: Mapped[int] = mapped_column(ForeignKey("sales_orders.id", ondelete="RESTRICT"), nullable=False, index=True)
    # Explicit short FK names: MySQL identifiers are limited to 64 chars.
    sales_order_line_id: Mapped[int] = mapped_column(
        ForeignKey("sales_order_lines.id", ondelete="RESTRICT", name="fk_sales_order_line_fulfilments_sales_order_line_id"),
        nullable=False,
    )
    unit_of_measure_id: Mapped[int] = mapped_column(
        ForeignKey("units_of_measure.id", ondelete="RESTRICT", name="fk_sales_order_line_fulfilments_unit_of_measure_id"),
        nullable=False,
    )
    # What Inventory reported as still available for this line (after
    # earlier lines of the same order took theirs) -- kept for the record.
    fg_available_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    fg_covered_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    production_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    result: Mapped[str] = mapped_column(String(20), nullable=False)
    assessed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class ProductionRequirement(Base, TimestampMixin, OrganisationScopedMixin):
    """Production demand for one Sales Order line's shortfall. Production
    owns it; it cannot change the Sales Order. `quantity` is in the
    product's own unit (the BOM's base unit too). One per line."""

    __tablename__ = "production_requirements"
    __table_args__ = (
        UniqueConstraint("sales_order_line_id", name="uq_production_requirements_sales_order_line_id"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    sales_order_id: Mapped[int] = mapped_column(ForeignKey("sales_orders.id", ondelete="RESTRICT"), nullable=False, index=True)
    sales_order_line_id: Mapped[int] = mapped_column(ForeignKey("sales_order_lines.id", ondelete="RESTRICT"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    unit_of_measure_id: Mapped[int] = mapped_column(ForeignKey("units_of_measure.id", ondelete="RESTRICT"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    # Snapshot of the product's active BOM when this was created (S15.1):
    # later BOM edits never change it. Null while `bom_required`.
    bom_id: Mapped[int | None] = mapped_column(ForeignKey("boms.id", ondelete="SET NULL"), nullable=True)
    bom_base_quantity: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    # Production P1: when the demand was satisfied or withdrawn, and why
    # it was withdrawn. Who is in the audit trail.
    fulfilled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    components: Mapped[list["ProductionRequirementComponent"]] = relationship(
        cascade="all, delete-orphan", order_by="ProductionRequirementComponent.id"
    )
    # Read-only: the commercial side stays on the Sales Order.
    sales_order = relationship("SalesOrder", viewonly=True, lazy="joined")

    @property
    def required_by_date(self) -> date | None:
        """The Sales Order's requested delivery date, read live (S15.1)."""
        return self.sales_order.requested_delivery_date if self.sales_order is not None else None


class ProductionRequirementComponent(Base):
    """One BOM component as it was when the requirement was created: the
    raw material, its quantity per BOM base quantity, and the raw
    material's own unit at that moment. Raw material needs are derived
    from it later (bom_service.required_quantity); nothing is allocated."""

    __tablename__ = "production_requirement_components"
    __table_args__ = (
        UniqueConstraint(
            "production_requirement_id", "raw_material_id", name="uq_production_requirement_components_requirement_material"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    production_requirement_id: Mapped[int] = mapped_column(
        ForeignKey("production_requirements.id", ondelete="CASCADE", name="fk_production_requirement_components_requirement_id"),
        nullable=False,
        index=True,
    )
    raw_material_id: Mapped[int] = mapped_column(
        ForeignKey("raw_materials.id", ondelete="RESTRICT", name="fk_production_requirement_components_raw_material_id"),
        nullable=False,
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    unit_of_measure_id: Mapped[int] = mapped_column(
        ForeignKey("units_of_measure.id", ondelete="RESTRICT", name="fk_production_requirement_components_unit_of_measure_id"),
        nullable=False,
    )
