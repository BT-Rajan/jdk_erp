from decimal import Decimal

from sqlalchemy import Boolean, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import OrganisationScopedMixin, TimestampMixin


class UnitOfMeasure(Base, TimestampMixin, OrganisationScopedMixin):
    """The one authoritative unit definition for quantities across JDK
    (docs/modules/units_of_measure.md) -- audited against jdk_clean first
    (docs/audit/UNITS_OF_MEASURE_AUDIT.md): jdk_clean tried a real table
    with a factor_to_base conversion column, removed it within a week for
    conflating a true physical ratio (ton->kg) with a business-specific
    packaging assumption ("bag->kg... edit if wrong for what's actually
    being bagged") in one field, and settled on a small hardcoded enum
    with no conversion at all -- duplicated three times (a Python tuple,
    a DB ENUM, and a frontend TS const) with no single source of truth.

    `dimension` + `conversion_factor_to_base` are added here for BOM
    (docs/modules/boms.md, docs/audit/BOMS_AUDIT.md) -- this is
    deliberately only the *safe half* of what jdk_clean removed: a pure,
    universal, dimensional ratio (kg/g/tonne all share dimension="mass";
    litre/ml share dimension="volume"), true regardless of what material
    is being measured. It is NOT the half that failed -- a
    business-specific packaging/density assumption (bag->kg, litre-of-
    this-material->kg) is never stored here; that lives on
    `RawMaterial.alternate_conversion_*` instead, scoped to the one
    material it's actually true for (docs/audit/BOMS_AUDIT.md #5).
    `dimension` is a free-form string, not a fixed enum -- an
    organisation may define whatever dimension families it needs (mass,
    volume, count, length, ...), matching the free-form module_key/action
    precedent already used for permissions. Both columns are nullable
    and must be both-null or both-set: a unit that doesn't participate
    in universal conversion (e.g. "pcs") simply carries neither.

    `code` is required and unique per organisation -- unlike Category,
    where the short code is optional, a unit's whole reason for existing
    is its stable short code (KG, TON, ...), and normalizing it
    (upper-cased, stripped) directly guards against the exact
    "kg"/"Kg"/"KGS" drift jdk_clean's own history shows free text
    produces."""

    __tablename__ = "units_of_measure"
    __table_args__ = (
        UniqueConstraint("organisation_id", "name", name="uq_units_of_measure_organisation_id_name"),
        UniqueConstraint("organisation_id", "code", name="uq_units_of_measure_organisation_id_code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    dimension: Mapped[str | None] = mapped_column(String(40), nullable=True)
    conversion_factor_to_base: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1", nullable=False)
