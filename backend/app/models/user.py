from datetime import datetime

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import OrganisationScopedMixin, TimestampMixin


class User(Base, TimestampMixin, OrganisationScopedMixin):
    """Pure identity, per docs/modules/authentication.md #2 -- exactly the
    fields authentication needs and nothing else. No role, department or
    profile fields here: those belong to the RBAC/user-management layer
    built next, on top of this table, not inside it (see
    docs/audit/AUTHENTICATION_AUDIT.md #6-7 for why that boundary matters)."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1", nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
