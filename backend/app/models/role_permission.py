from sqlalchemy import String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import OrganisationScopedMixin, TimestampMixin


class RolePermission(Base, TimestampMixin, OrganisationScopedMixin):
    """The role-level default grant (docs/modules/permissions.md #4):
    within an organisation, this role may perform this action on this
    module, at this scope. module_key/action are free-form strings, not
    an enum -- see docs/audit/PERMISSIONS_AUDIT.md for why a fixed
    catalog isn't reused from jdk_clean."""

    __tablename__ = "role_permissions"
    __table_args__ = (
        UniqueConstraint("organisation_id", "role", "module_key", "action", name="uq_role_permissions_scope_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    module_key: Mapped[str] = mapped_column(String(50), nullable=False)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    scope: Mapped[str] = mapped_column(String(10), nullable=False)
