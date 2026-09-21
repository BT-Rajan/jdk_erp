from sqlalchemy import Boolean, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import OrganisationScopedMixin, TimestampMixin


class Team(Base, TimestampMixin, OrganisationScopedMixin):
    """Organisational grouping only (docs/modules/teams.md #1/#4/#5) --
    deliberately carries no permission data. jdk_clean's equivalent
    (Department) doubled as the row axis of a page-permission matrix
    (department_permissions, see docs/audit/TEAMS_AUDIT.md); that coupling
    is not reused here. RBAC decides scope x permission on its own tables,
    referencing Team only as a plain foreign key."""

    __tablename__ = "teams"
    __table_args__ = (
        UniqueConstraint("organisation_id", "name", name="uq_teams_organisation_id_name"),
        UniqueConstraint("organisation_id", "code", name="uq_teams_organisation_id_code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    code: Mapped[str | None] = mapped_column(String(30), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1", nullable=False)
