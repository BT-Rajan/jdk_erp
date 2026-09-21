from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import OrganisationScopedMixin, TimestampMixin


class User(Base, TimestampMixin, OrganisationScopedMixin):
    """Pure identity, per docs/modules/authentication.md #2 -- exactly the
    fields authentication needs and nothing else. No role or profile
    fields here: those belong to the RBAC/user-management layer built
    next, on top of this table, not inside it (see
    docs/audit/AUTHENTICATION_AUDIT.md #6-7 for why that boundary
    matters). team_id is the one exception -- docs/modules/users.md #2
    lists it as part of the core identity record, and docs/modules/teams.md
    #3 fixes it at one user -> one team, not a permission relationship."""

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
    # Nullable -- a user may not be assigned to a team yet (docs/modules/teams.md
    # #3). No cross-organisation FK risk: assignment only ever happens
    # through app code that already scopes the team lookup to the user's
    # own organisation (see app/api/users.py, scripts/seed_admin.py).
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), nullable=True, index=True)
