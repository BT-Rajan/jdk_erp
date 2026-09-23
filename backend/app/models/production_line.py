from sqlalchemy import Boolean, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import OrganisationScopedMixin, TimestampMixin


class ProductionLine(Base, TimestampMixin, OrganisationScopedMixin):
    """The production flow/resource a Machine runs on
    (docs/modules/machines.md) -- audited against jdk_clean first
    (docs/audit/MACHINES_AUDIT.md): jdk_clean has no separate production-
    line concept at all -- its one `machines` table IS the production
    line, labelled "Production Line" in the UI while the model/table keep
    the internal name "machine," with a hard-coded singleton check
    rejecting a second row. That conflation is deliberately not followed
    here -- Machine and ProductionLine are genuinely separate identities,
    a Machine referencing a ProductionLine by FK, even though JDK
    currently has exactly one of each. No singleton constraint is
    enforced either: ordinary admin-gated CRUD already produces "exactly
    one" today without a special-cased business rule that would need
    relaxing the moment a second line or machine is added.

    Deliberately tiny -- code/name/status/organisation only, matching the
    spec's own field list (docs/modules/machines.md #6). No line
    balancing, work centres, routing, or hierarchy of any kind."""

    __tablename__ = "production_lines"
    __table_args__ = (
        UniqueConstraint("organisation_id", "code", name="uq_production_lines_organisation_id_code"),
        UniqueConstraint("organisation_id", "name", name="uq_production_lines_organisation_id_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1", nullable=False)
