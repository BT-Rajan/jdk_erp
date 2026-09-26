from decimal import Decimal

from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import OrganisationScopedMixin, TimestampMixin


class Product(Base, TimestampMixin, OrganisationScopedMixin):
    """The authoritative definition of what JDK sells and manufactures
    (docs/modules/products.md) -- audited against jdk_clean first
    (docs/audit/PRODUCTS_AUDIT.md). jdk_clean's own ~20-field Product is
    already fairly disciplined (no variant builder, no attribute editor,
    no bundles); this keeps only what the audit confirmed is real:
    `category`/`unit` are free-text/enum in jdk_clean (a decision it
    later reversed away from a real units_of_measure master it had
    briefly built) -- here they're required FKs to jdk_erp's own
    Category/UnitOfMeasure masters instead, since both already exist.
    `tags`/`properties` (jdk_clean's own comments: "not read by any
    business logic") are dropped entirely. `reference_cost` is omitted --
    jdk_clean has no cost field on Product at all, so there's no existing
    business rule to preserve. `product_type` (finished_good/sub_assembly
    in jdk_clean) is also deliberately deferred: its only real consumer
    is BOM's component polymorphism, and BOM doesn't exist in this
    codebase yet -- adding it now would be speculative (Principle 5,
    the same reasoning Suppliers applied to defer its Material
    relationship). No barcode/weight -- the audit found neither field
    exists anywhere in jdk_clean, and jdk_erp has no logistics/Delivery
    consumer for either yet.

    `code` is system-generated (`app/core/id_formats.PRODUCT_CODE`) and
    immutable after creation (no update path for it at all) -- per
    explicit user instruction that every Phase 2 master's code be
    auto-assigned, superseding this module's original manually-entered
    code (the audit found jdk_clean's own Product code was manually
    assigned; that precedent no longer applies). `code` is absent from
    ProductUpdateRequest either way.

    `customer_lead_time_days` and `manufacturing_lead_time_days` are
    deliberately distinct, simple reference values -- jdk_clean has
    NEITHER field (a confirmed gap, not something reused): Sales there
    negotiates `Order.requested_delivery_date` by hand with no read from
    Product at all, and "manufacturing time" is expressed only as a rate
    (hours/unit) feeding a live capacity-scheduling engine internal to
    Feasibility. Building that scheduling engine here would be wildly out
    of scope for a ~20-product master; instead this follows the user's
    own explicit architecture diagram exactly -- Product carries the two
    simple reference numbers, and a future Feasibility/Quotation/Order
    module is responsible for turning them into an actual commitment
    date, snapshotting whatever value it used onto its own transaction
    row (never a live re-read of Product) so a later change here can
    never rewrite history, the same discipline Customer/Supplier already
    apply to phone normalization and jdk_clean's own real (correct)
    quotation/order line-item price snapshotting.

    `selling_price` is the current/default reference price only --
    real quotation/order line items (once built) own their own price
    column, never a live FK-derived value, matching jdk_clean's own
    correct OrderDetail/QuotationDetail pattern."""

    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("organisation_id", "code", name="uq_products_organisation_id_code"),
        UniqueConstraint("organisation_id", "name", name="uq_products_organisation_id_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    category_id: Mapped[int] = mapped_column(
        ForeignKey("categories.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    unit_of_measure_id: Mapped[int] = mapped_column(
        ForeignKey("units_of_measure.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    selling_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    # Admin-set permitted quoting range (Sales S4). A quotation line priced
    # outside it -- or for a product with no range set -- is flagged as
    # needing Admin approval; never blocked, never silently accepted.
    # Both optional; when both are set, min <= max.
    min_selling_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    max_selling_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    # Production staff needed to produce this product -- the Admin-set
    # figure the 0-2 working-day manpower check sums. NULL = not set.
    production_staff_required: Mapped[int | None] = mapped_column(Integer, nullable=True)
    manufacturing_lead_time_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    customer_lead_time_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1", nullable=False)
