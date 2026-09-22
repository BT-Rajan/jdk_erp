from sqlalchemy import Boolean, String, Text, UniqueConstraint
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

    This model fixes the "no single source of truth" problem (an actual
    admin-manageable table, not a hardcoded enum) without reintroducing
    the conversion mechanism that failed: there is deliberately no
    factor/ratio/category column here. `code` is required and unique per
    organisation -- unlike Category, where the short code is optional,
    a unit's whole reason for existing is its stable short code (KG,
    TON, ...), and normalizing it (upper-cased, stripped) directly
    guards against the exact "kg"/"Kg"/"KGS" drift jdk_clean's own
    history shows free text produces."""

    __tablename__ = "units_of_measure"
    __table_args__ = (
        UniqueConstraint("organisation_id", "name", name="uq_units_of_measure_organisation_id_name"),
        UniqueConstraint("organisation_id", "code", name="uq_units_of_measure_organisation_id_code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1", nullable=False)
