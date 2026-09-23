from decimal import Decimal

from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import TimestampMixin


class SupplierMaterial(Base, TimestampMixin):
    """Which suppliers can provide which raw material, and on what terms
    -- the one relationship the user asked to be built with real depth
    (docs/modules/raw_materials.md #6/#7). Reproduces jdk_clean's own
    `supplier_materials` table near-exactly (docs/audit/RAW_MATERIALS_AUDIT.md
    #5) -- it's a well-designed table there, just under-consumed (its
    `purchase_price` is never actually read into anything downstream in
    jdk_clean, since PO doesn't read it either).

    No `organisation_id` of its own -- like `UserTeam`, this is a join
    row between two already organisation-scoped entities
    (`Supplier`, `RawMaterial`); the API layer validates both belong to
    the caller's own organisation (and, implicitly, to each other) rather
    than this table carrying a third, redundant copy of that fact.

    `is_preferred` is enforced service-side only, matching jdk_clean's
    own real, deliberate choice -- at most one active row per
    `raw_material_id` may be preferred; setting one silently un-sets any
    other, never a DB constraint or a rejected write (see
    app/api/raw_material_suppliers.py's `_enforce_single_preferred`).

    A material may have zero, one, or many suppliers -- no minimum is
    enforced, matching jdk_clean's own confirmed behaviour (a "no
    suppliers linked yet" empty state is normal, not an error state).

    Dropped from jdk_clean's version: `currency` (this codebase's
    `Organisation.currency` is already the one place currency is
    recorded; a redundant per-row currency invents multi-currency
    support with no evidence it's needed), `onboarded_at`/
    `last_transaction_at` (both are only ever written by an actual
    Purchase Order receipt in jdk_clean -- Purchase Order/Receipt don't
    exist in this codebase yet, so these would be dead columns with no
    writer; add them when that module exists to write them), and any
    soft-delete/status-vs-deleted distinction (jdk_clean separately
    tracks "paused" via `status` and "severed" via `deleted_at` --
    nothing in this codebase yet needs that distinction, since no
    transaction table exists to reference a severed relationship
    historically; `is_active` alone covers "paused," and severing a
    relationship here is a real DELETE).

    No Purchase UoM/conversion factor either, for the same reason
    RawMaterial itself omits one -- see that model's docstring."""

    __tablename__ = "supplier_materials"
    __table_args__ = (
        UniqueConstraint("supplier_id", "raw_material_id", name="uq_supplier_materials_supplier_id_raw_material_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id", ondelete="CASCADE"), nullable=False, index=True)
    raw_material_id: Mapped[int] = mapped_column(
        ForeignKey("raw_materials.id", ondelete="CASCADE"), nullable=False, index=True
    )
    supplier_material_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    purchase_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    lead_time_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    moq: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    max_supply_quantity: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    is_preferred: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1", nullable=False)
