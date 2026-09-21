from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.roles import TEAM_MEMBER
from app.models.mixins import OrganisationScopedMixin, TimestampMixin


class User(Base, TimestampMixin, OrganisationScopedMixin):
    """Pure identity, per docs/modules/authentication.md #2 -- exactly the
    fields authentication needs and nothing else. Team membership is NOT
    a column here -- docs/modules/roles_rbac.md #1 makes it many-to-many
    (see app/models/user_team.py), replacing an earlier team_id column
    that assumed one team per user. role is a plain string, not a FK into
    a roles table -- docs/modules/roles_rbac.md's implementation section
    on why a fixed four-value set doesn't need one. No permission data of
    any kind lives on this table (docs/audit/AUTHENTICATION_AUDIT.md #6-7,
    docs/modules/users.md #5)."""

    __tablename__ = "users"
    __table_args__ = (
        # The query the directory endpoints actually run ("active users in
        # my organisation") -- docs/modules/users.md #9.
        Index("ix_users_organisation_id_is_active", "organisation_id", "is_active"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1", nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default=TEAM_MEMBER)
