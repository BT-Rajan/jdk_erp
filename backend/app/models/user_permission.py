from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import OrganisationScopedMixin, TimestampMixin


class UserPermission(Base, TimestampMixin, OrganisationScopedMixin):
    """A per-user override on top of the role default
    (docs/modules/permissions.md #5/#6) -- e.g. giving one Team Member
    TEAM scope on one module without changing their role or affecting
    anyone else. A separate table rather than a nullable role/user_id
    column on one polymorphic table, since a partial unique index isn't
    portable to MySQL (this project's production target)."""

    __tablename__ = "user_permissions"
    __table_args__ = (UniqueConstraint("user_id", "module_key", "action", name="uq_user_permissions_scope_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    module_key: Mapped[str] = mapped_column(String(50), nullable=False)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    scope: Mapped[str] = mapped_column(String(10), nullable=False)
