from sqlalchemy import Boolean, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import OrganisationScopedMixin, TimestampMixin


class Supplier(Base, TimestampMixin, OrganisationScopedMixin):
    """The vendor master consumed by Procurement (docs/modules/suppliers.md)
    -- audited against jdk_clean first (docs/audit/SUPPLIERS_AUDIT.md).
    Expected volume is ~10 per organisation, so this is deliberately the
    lightest master built so far: no onboarding workflow, no rating, no
    ID-document verification, no per-supplier approval-threshold overrides
    -- jdk_clean carries all of those (mostly copy-pasted from its own
    Customer model) with no real consumer. There is also deliberately no
    supplier<->material relationship yet (jdk_clean's real
    `supplier_materials` join table is solid prior art worth reusing
    *when Raw Materials/Products exist in jdk_erp* -- they don't yet, so
    building the other half of that relationship now would be speculative
    (Principle 5); Procurement links a supplier to a material when that
    module is built.

    Flat contact fields only (contact_person/phone/email/address), same
    shape jdk_clean itself uses for Supplier -- no multi-contact/
    multi-address child tables. `code` is auto-generated
    (app/core/id_formats.py SUPPLIER_ID), same mechanism as Customer.
    `name` is unique per organisation, unlike Customer -- a supplier is a
    small, internally curated vendor list (closer to Category/Unit in
    spirit), not externally-given high-volume business data, so two
    accidental "Acme Traders" rows are worth blocking rather than
    tolerating. `phone` is normalized to digits-only at write time (see
    app/schemas/supplier.py) and enforced unique per organisation when
    provided, the same fix Customer already applies to jdk_clean's O(n)
    duplicate-phone scan. Every mutation is admin-gated (create/edit/
    activate-deactivate) -- unlike Customer, there is no ownership/
    assignment dimension here at all, so this reuses Category/Unit's
    exact admin-gated shape rather than the permission-scope engine."""

    __tablename__ = "suppliers"
    __table_args__ = (
        UniqueConstraint("organisation_id", "code", name="uq_suppliers_organisation_id_code"),
        UniqueConstraint("organisation_id", "name", name="uq_suppliers_organisation_id_name"),
        UniqueConstraint("organisation_id", "phone", name="uq_suppliers_organisation_id_phone"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(10), nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    contact_person: Mapped[str | None] = mapped_column(String(120), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    email: Mapped[str | None] = mapped_column(String(120), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1", nullable=False)
