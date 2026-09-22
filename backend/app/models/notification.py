from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import TimestampMixin

# Fixed, generic set (docs/modules/notifications.md #5) -- a plain
# string, not a database enum, same MySQL/SQLite-portability reasoning
# as every other fixed-set column in this project (audit_events.action,
# jobs.status, users.role, ...). Modules provide the actual title/
# message; this only carries the type through to the UI's icon/tone.
INFO = "INFO"
ACTION_REQUIRED = "ACTION_REQUIRED"
SUCCESS = "SUCCESS"
WARNING = "WARNING"
ERROR = "ERROR"

VALID_TYPES = {INFO, ACTION_REQUIRED, SUCCESS, WARNING, ERROR}


class Notification(Base, TimestampMixin):
    """One row per notification (docs/modules/notifications.md #2).
    Not OrganisationScopedMixin -- every real query here filters by
    recipient_user_id, not organisation_id (docs/modules/notifications.md
    #4: a user only ever sees their own notifications); organisation_id
    is still stored for the email job's benefit (it needs it to look up
    that organisation's mailbox) and for defense-in-depth, not as the
    primary scope. CASCADE on recipient_user_id -- a notification is
    meaningless once its recipient is gone, unlike an audit event, which
    must outlive the user it references (SET NULL there instead)."""

    __tablename__ = "notifications"
    __table_args__ = (
        # The exact shape of list_for_user()/unread_count()'s query --
        # this user's notifications, optionally unread-only, newest first.
        Index("ix_notifications_recipient_user_id_is_read", "recipient_user_id", "is_read"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organisation_id: Mapped[int] = mapped_column(
        ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    recipient_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    message: Mapped[str] = mapped_column(String(1000), nullable=False)
    # A reference to the business record this is about -- an id, never
    # a copy of it (docs/modules/notifications.md #6), same convention
    # as jobs.payload and audit_events.entity_type/entity_id.
    entity_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
