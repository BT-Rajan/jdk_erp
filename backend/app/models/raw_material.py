from decimal import Decimal

from sqlalchemy import Boolean, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import OrganisationScopedMixin, TimestampMixin


class RawMaterial(Base, TimestampMixin, OrganisationScopedMixin):
    """The authoritative material identity bridging Supplier -> Purchase
    Order -> Receipt -> Inventory on one side, and BOM -> Production on
    the other (docs/modules/raw_materials.md) -- audited against
    jdk_clean first (docs/audit/RAW_MATERIALS_AUDIT.md). Deliberately as
    lean as Category/Unit/Supplier: ~5 materials exist at JDK, and the
    user's own instruction is explicit -- "keep the master lean; make the
    relationships strong." The relationship that actually needed real
    depth (Supplier <-> Raw Material) lives in SupplierMaterial below,
    not as extra columns here.

    Every field jdk_clean's own comments confirm is decorative/unused is
    dropped: `material_type` ("doesn't change how it's stocked/
    purchased/consumed anywhere downstream"), `manufacturer`/
    `manufacturer_part_number` (pure display, no consumer), `properties`
    (a JSON attribute bag, "not read by any business logic" -- per the
    spec's own #16, two operationally different materials should be
    distinct authoritative records with their own code, not variants
    distinguished by a free-form attribute bag), `inspection_required`/
    `certificate_required`/`qc_notes` (never actually checked at receipt
    in jdk_clean despite existing), `storage_location` (a single-location
    string superseded by a real warehouse/location concept once
    Inventory exists), and `reorder_point`/`safety_stock`/
    `maximum_stock` (Inventory-consumption thresholds -- Inventory
    doesn't exist in this codebase yet; add them there, not here, the
    same "defer until a real consumer exists" reasoning already applied
    to Supplier's Material relationship and Product's product_type).

    No `default_supplier_id` either -- jdk_clean carries this *in
    addition to* `supplier_materials.is_preferred`, a second, harder-to-
    keep-in-sync source of truth for the same fact (Principle 2). This
    codebase's `SupplierMaterial.is_preferred` is the one place "which
    supplier is preferred for this material" is recorded.

    `reference_cost` is the one commercial field kept, unlike Product
    (which has none) -- jdk_clean's `raw_materials.unit_cost` is
    genuinely consumed (default price when a Purchase Order line is
    created, and inventory valuation), a real business rule worth
    preserving even though Purchase Order/Inventory don't exist in this
    codebase yet. It is a current/default reference value only, same
    discipline as Product.selling_price -- a future Purchase Order line
    must snapshot its own price, never read this live for a historical
    record.

    `category_id`/`unit_of_measure_id` are required FKs to the existing
    Category/UnitOfMeasure masters, not jdk_clean's free-text/enum
    (jdk_clean tried a real units-of-measure table once and reverted it,
    same history already found for Product) -- validated active and
    same-organisation on every write, exactly like Product.

    No Purchase UoM/conversion factor -- jdk_clean has no such concept at
    all despite live procurement (a confirmed gap, not prior art), and
    the spec's own instruction is explicit: don't build a conversion
    engine without a proven need. If JDK's real procurement ever needs
    "stocked in KG, purchased in BAG," it belongs on SupplierMaterial
    (per-relationship, since the conversion is inherently
    supplier/packaging-specific), not here -- deferred until that need is
    proven."""

    __tablename__ = "raw_materials"
    __table_args__ = (
        UniqueConstraint("organisation_id", "code", name="uq_raw_materials_organisation_id_code"),
        UniqueConstraint("organisation_id", "name", name="uq_raw_materials_organisation_id_name"),
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
    reference_cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1", nullable=False)
