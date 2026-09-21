from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AuthEventType(str, Enum):
    LOGIN_SUCCESS = "login_success"
    LOGIN_FAILURE = "login_failure"
    LOGOUT = "logout"
    PASSWORD_CHANGE = "password_change"
    # docs/modules/session_security.md #14 -- security-sensitive changes,
    # not just authentication events.
    ROLE_CHANGED = "role_changed"
    TEAM_ADDED = "team_added"
    TEAM_REMOVED = "team_removed"


class AuthEvent(Base):
    """The authentication/security audit trail jdk_clean was missing
    entirely (docs/audit/AUTHENTICATION_AUDIT.md #3/#7): every login
    success/failure, logout, password change, role change and
    team-membership change, independent of the generic business-record
    audit_log a later module will add. Doubles as the login-lockout
    counter -- see app/services/auth_service.py -- so lockout state has
    exactly one source of truth instead of a second, separate table to
    keep in sync."""

    __tablename__ = "auth_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # The user this event is *about* -- e.g. whose role changed.
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    # Who *performed* the action, when different from user_id (an admin
    # changing someone else's role). None for self-caused events where
    # the actor is unambiguous (a user logging themselves in).
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    username_attempted: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    reason: Mapped[str | None] = mapped_column(String(30), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)
