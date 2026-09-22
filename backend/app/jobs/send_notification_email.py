from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleError
from app.core.job_registry import RetryableJobError, register_job_handler
from app.models.notification import Notification
from app.models.user import User
from app.services import email_service

JOB_TYPE = "send_notification_email"


def run(db: Session, payload: dict) -> None:
    """The one real email-sending job (docs/modules/notifications.md #7)
    -- notify(..., send_email=True) dispatches this instead of sending
    inline, so the request that created the notification never blocks
    on SMTP. The email body is the same title/message the caller already
    chose for the in-app notification (docs/modules/notifications.md
    #10) -- no separate, richer email template that could leak more.

    Not retryable by construction when there's nothing to do: a
    notification or user deleted before this ran, an inactive user, or
    an organisation with no mailbox configured are all "nothing to
    send," not failures. A genuine SMTP failure (email_service.send_email
    raising BusinessRuleError) *is* retried -- the standard "temporary
    email failure" case docs/modules/background_jobs.md #6 calls for."""
    notification = db.get(Notification, payload["notification_id"])
    if notification is None:
        return

    user = db.get(User, notification.recipient_user_id)
    if user is None or not user.is_active:
        return

    if not email_service.is_configured(db, notification.organisation_id):
        return

    try:
        email_service.send_email(
            db,
            notification.organisation_id,
            user.email,
            subject=notification.title,
            body=notification.message,
        )
    except BusinessRuleError as exc:
        raise RetryableJobError(str(exc)) from exc


register_job_handler(JOB_TYPE, run)
