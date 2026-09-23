from decimal import Decimal

from sqlalchemy import Boolean, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import OrganisationScopedMixin, TimestampMixin


class Warehouse(Base, TimestampMixin, OrganisationScopedMixin):
    """The authoritative physical storage location inside the JDK
    factory and its configured total storage capacity
    (docs/modules/warehouses.md) -- audited against jdk_clean first
    (docs/audit/WAREHOUSES_AUDIT.md). Unlike every prior master, jdk_clean
    has **no warehouse/location entity at all** -- "warehouse" there is
    only a department/permission label (one row in its generic
    `departments` table, used solely to gate which users see
    warehouse-scoped dashboard notifications), never a data row with its
    own identity, capacity, or lifecycle. This model is therefore
    genuinely new, built directly from the spec rather than refactored
    from any jdk_clean design.

    `total_usable_storage_area` + `storage_area_unit_of_measure_id`
    (reusing jdk_erp's own existing UnitOfMeasure master, same as
    Machine's capacity unit) are the one important addition: a
    structured, configurable total capacity value, never hard-coded and
    never a free-text string. Deliberately NOT built here: any
    "required area" or "available area" calculation
    (`total - required = available`) -- jdk_clean has zero evidence of a
    per-material/per-product storage-area-requirement concept anywhere
    (the audit's only near-miss, `raw_materials.storage_location`, is a
    free-text bin label explicitly confirmed unused by any business
    logic), and even if such a field existed, there is no Inventory/
    Stock Ledger in this codebase yet to supply the live stock
    quantities the calculation needs -- required area is fundamentally
    uncomputable without them. Both the storage-requirement field (on
    Product/RawMaterial) and the required/available-area formula are
    documented in the module spec as binding targets for whenever
    Inventory is built, per the same "defer until a real consumer
    exists" discipline already applied to Machine's production-time
    formula and Supplier's Material relationship.

    No hierarchical location (zone/aisle/rack/bin), no address/GPS/
    logistics fields, no warehouse-in/out or stock-movement tables --
    none of that exists in jdk_clean either, and none has a proven JDK
    requirement. No singleton constraint is enforced, and no special
    deactivation guard exists yet either -- there are no inventory
    operations in this codebase yet for deactivating the only warehouse
    to break; that guard belongs to whichever future Inventory module
    actually depends on an active warehouse to record movements against.

    `code` is system-generated (`app/core/id_formats.WAREHOUSE_CODE`)
    and immutable after creation, per explicit user instruction that
    every Phase 2 master's code be auto-assigned."""

    __tablename__ = "warehouses"
    __table_args__ = (
        UniqueConstraint("organisation_id", "code", name="uq_warehouses_organisation_id_code"),
        UniqueConstraint("organisation_id", "name", name="uq_warehouses_organisation_id_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    total_usable_storage_area: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    storage_area_unit_of_measure_id: Mapped[int] = mapped_column(
        ForeignKey("units_of_measure.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1", nullable=False)
