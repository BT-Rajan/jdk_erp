"""Production Plan (P3 -- MRP / Production Planning): an accepted decision
of *what to produce, how much and why*. Not a Production Order, not a
schedule, never an inventory movement.

- `source_type` `customer_demand`: made for one Production Requirement
  (its Sales Order line and required-by date are read through it, live);
  `independent`: production with no customer behind it (building stock,
  management decision) -- no fake Sales Order or requirement is created.
- Several plans may serve one requirement; a second active one must be
  asked for explicitly (`additional`), never created by accident. A plan
  may intentionally exceed the demand -- the excess is free production and
  is never assigned to a customer.
- Lifecycle: `draft` (editable) -> `planned` (accepted) ; either ->
  `cancelled` (reason, kept). Planned and cancelled plans are not edited.
- The planning basis is kept: the BOM snapshot (base quantity and each
  component in its raw material's own unit), taken from the requirement's
  snapshot or the product's active BOM, never refreshed once taken.
- `original_quantity` is the quantity first planned; every change is
  audited (module `production`)."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import OrganisationScopedMixin, TimestampMixin

CUSTOMER_DEMAND = "customer_demand"
INDEPENDENT = "independent"
SOURCE_TYPES = (CUSTOMER_DEMAND, INDEPENDENT)

PLAN_DRAFT = "draft"
PLAN_PLANNED = "planned"
PLAN_CANCELLED = "cancelled"
PLAN_STATUSES = (PLAN_DRAFT, PLAN_PLANNED, PLAN_CANCELLED)
PLAN_ACTIVE = (PLAN_DRAFT, PLAN_PLANNED)


class ProductionPlan(Base, TimestampMixin, OrganisationScopedMixin):
    __tablename__ = "production_plans"
    __table_args__ = (
        CheckConstraint("planned_quantity > 0", name="planned_quantity_positive"),
        CheckConstraint("original_quantity > 0", name="original_quantity_positive"),
        CheckConstraint("source_type IN ('customer_demand', 'independent')", name="source_type_valid"),
        CheckConstraint("status IN ('draft', 'planned', 'cancelled')", name="status_valid"),
        CheckConstraint(
            "(source_type = 'customer_demand' AND production_requirement_id IS NOT NULL) "
            "OR (source_type = 'independent' AND production_requirement_id IS NULL)",
            name="source_reference",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT", name="fk_production_plans_product_id"), nullable=False, index=True
    )
    # The product's own stock unit (the BOM base unit).
    unit_of_measure_id: Mapped[int] = mapped_column(
        ForeignKey("units_of_measure.id", ondelete="RESTRICT", name="fk_production_plans_unit_of_measure_id"), nullable=False
    )
    planned_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    original_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)
    production_requirement_id: Mapped[int | None] = mapped_column(
        ForeignKey("production_requirements.id", ondelete="RESTRICT", name="fk_production_plans_requirement_id"),
        nullable=True,
        index=True,
    )
    # A deliberate second (or further) plan for the same requirement.
    additional: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Independent plans only; a customer plan reads its Sales Order's date.
    required_by_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=PLAN_DRAFT)
    bom_id: Mapped[int | None] = mapped_column(ForeignKey("boms.id", ondelete="SET NULL", name="fk_production_plans_bom_id"), nullable=True)
    bom_base_quantity: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL", name="fk_production_plans_created_by_user_id"), nullable=True
    )
    planned_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    components: Mapped[list["ProductionPlanComponent"]] = relationship(
        cascade="all, delete-orphan", order_by="ProductionPlanComponent.id"
    )
    requirement = relationship("ProductionRequirement", viewonly=True, lazy="joined")


class ProductionPlanComponent(Base):
    """One BOM component as it stood when the plan took its snapshot: the
    raw material, its quantity per BOM base quantity, and the material's
    own unit then."""

    __tablename__ = "production_plan_components"

    id: Mapped[int] = mapped_column(primary_key=True)
    production_plan_id: Mapped[int] = mapped_column(
        ForeignKey("production_plans.id", ondelete="CASCADE", name="fk_production_plan_components_plan_id"), nullable=False, index=True
    )
    raw_material_id: Mapped[int] = mapped_column(
        ForeignKey("raw_materials.id", ondelete="RESTRICT", name="fk_production_plan_components_raw_material_id"), nullable=False
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    unit_of_measure_id: Mapped[int] = mapped_column(
        ForeignKey("units_of_measure.id", ondelete="RESTRICT", name="fk_production_plan_components_unit_of_measure_id"), nullable=False
    )
