from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import OrganisationScopedMixin, TimestampMixin

DRAFT = "draft"
ACTIVE = "active"
BOM_STATUSES = (DRAFT, ACTIVE)


class Bom(Base, TimestampMixin, OrganisationScopedMixin):
    """The single, unambiguous relationship between a finished Product
    and the Raw Materials required to produce a specified base quantity
    of it (docs/modules/boms.md) -- audited against jdk_clean first
    (docs/audit/BOMS_AUDIT.md). Hardens jdk_clean's own real, sound
    design (`boms.product_id UNIQUE` -- exactly one BOM per product, no
    revision/version history, "active/inactive" meaning "is this
    currently the authoritative recipe" not draft-vs-approved) rather
    than inventing a new BOM model or a versioning system the spec
    explicitly says not to build without evidence.

    `base_quantity` is expressed in the Product's own `unit_of_measure_id`
    -- there is deliberately no separate stored base-UoM column here; the
    spec is explicit that "the Product's configured stock/base UoM
    should be used rather than allowing an unrelated arbitrary UoM," so
    storing a second, potentially-diverging UoM reference here would be
    exactly the kind of duplicated source of truth Principle 2 forbids.

    `status` is `draft`/`active`, not jdk_clean's `active`/`inactive` --
    renamed for clarity, since a not-yet-`active` BOM here really is
    "still being built," not "temporarily disabled" (BOM has no ongoing
    operational lifecycle to pause the way a Machine or Warehouse does).
    Activation requires passing full validation (docs/modules/boms.md
    #9) -- at least one component, every component's quantity positive,
    and a resolvable UoM conversion for every component -- enforced in
    app/api/boms.py, not here.

    No `scrap_percent`/wastage field is carried over from jdk_clean --
    real and working there, but outside the exact formula this module's
    spec gives ("Required Material = Component Qty x Production Qty /
    Base Qty," with no scrap multiplier); flagged in the audit as a
    deliberately deferred decision, not an oversight."""

    __tablename__ = "boms"
    __table_args__ = (UniqueConstraint("organisation_id", "product_id", name="uq_boms_organisation_id_product_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True)
    base_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default=DRAFT, server_default=DRAFT)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class BomComponent(Base, TimestampMixin):
    """One Raw Material required by a BOM, in the material's own
    `unit_of_measure_id` -- never a percentage, never a separately
    selectable UoM (docs/modules/boms.md #1/#4/#6). No `organisation_id`
    of its own -- a join between a `Bom` (already organisation-scoped)
    and a `RawMaterial`, the same shape this codebase's own `UserTeam`/
    `SupplierMaterial` already use for pure relationship rows.

    Unique per `(bom_id, raw_material_id)` -- jdk_clean prevents
    duplicate components at the application layer only; this hardens
    that into a real DB constraint (docs/modules/boms.md #9)."""

    __tablename__ = "bom_components"
    __table_args__ = (
        UniqueConstraint("bom_id", "raw_material_id", name="uq_bom_components_bom_id_raw_material_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    bom_id: Mapped[int] = mapped_column(ForeignKey("boms.id", ondelete="CASCADE"), nullable=False, index=True)
    raw_material_id: Mapped[int] = mapped_column(
        ForeignKey("raw_materials.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
