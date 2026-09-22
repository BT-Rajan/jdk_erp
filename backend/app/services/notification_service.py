"""The one notification service every module calls
(docs/modules/notifications.md #1) -- notify(db, user_or_users, ...)
creates the record(s); this module also owns read-status and the one
authorization boundary that's actually enforceable here: a caller can
only ever list/read/mark-read their OWN notifications
(docs/modules/notifications.md #4). Whether a notification's *content*
is something its recipient is authorized to see is the calling module's
responsibility, exactly like app/core/entity_access.py's registration
hook for files -- this layer has no way to re-derive an arbitrary
future resource's own access rule.
"""

from datetime import datetime

from sqlalchemy.orm import Session

from app.models.notification import VALID_TYPES, Notification
from app.models.user import User


def notify(
    db: Session,
    recipients: User | list[User],
    *,
    type: str,
    title: str,
    message: str,
    entity_type: str | None = None,
    entity_id: int | None = None,
    target_url: str | None = None,
    send_email: bool = False,
) -> list[Notification]:
    """Does not commit -- same pattern as audit_service.log_event and
    job_service.dispatch (docs/modules/database_transaction_integrity.md
    #6): include this in the same transaction as the business change
    that caused it. send_email=False by default -- docs/modules/notifications.md
    #8's "don't create notifications for everything" applies doubly to
    email; an in-app notification is the default for a meaningful event,
    an email only for the subset a caller explicitly opts into."""
    if type not in VALID_TYPES:
        raise ValueError(f"Unknown notification type: {type!r}")

    people = [recipients] if isinstance(recipients, User) else recipients
    rows = [
        Notification(
            organisation_id=person.organisation_id,
            recipient_user_id=person.id,
            type=type,
            title=title,
            message=message,
            entity_type=entity_type,
            entity_id=entity_id,
            target_url=target_url,
        )
        for person in people
    ]
    db.add_all(rows)
    db.flush()

    if send_email:
        # Imported here, not at module level, to avoid a cycle:
        # notification_email_service dispatches a job whose handler
        # (app/jobs/send_notification_email.py) reads this same
        # Notification row back, so it can't import this module at
        # import time either.
        from app.services import notification_email_service

        for row in rows:
            notification_email_service.dispatch_email(db, row)

    return rows


def list_for_user(
    db: Session, user: User, *, unread_only: bool = False, skip: int = 0, limit: int = 50
) -> list[Notification]:
    query = db.query(Notification).filter(Notification.recipient_user_id == user.id)
    if unread_only:
        query = query.filter(Notification.is_read.is_(False))
    return query.order_by(Notification.created_at.desc(), Notification.id.desc()).offset(skip).limit(limit).all()


def unread_count(db: Session, user: User) -> int:
    return (
        db.query(Notification)
        .filter(Notification.recipient_user_id == user.id, Notification.is_read.is_(False))
        .count()
    )


def mark_read(db: Session, user: User, notification_id: int) -> Notification | None:
    """None (not an error) when the id doesn't exist or belongs to
    another user -- same "don't confirm what you can't see" shape as
    every other cross-boundary lookup in this codebase (e.g.
    app/api/users.py's get_user)."""
    row = (
        db.query(Notification)
        .filter(Notification.id == notification_id, Notification.recipient_user_id == user.id)
        .first()
    )
    if row is None:
        return None
    if not row.is_read:
        row.is_read = True
        row.read_at = datetime.utcnow()
        db.add(row)
    return row


def mark_all_read(db: Session, user: User) -> int:
    now = datetime.utcnow()
    return (
        db.query(Notification)
        .filter(Notification.recipient_user_id == user.id, Notification.is_read.is_(False))
        .update({"is_read": True, "read_at": now}, synchronize_session=False)
    )
