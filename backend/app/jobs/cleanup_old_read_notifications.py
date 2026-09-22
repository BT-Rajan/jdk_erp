from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.job_registry import register_job_handler
from app.models.notification import Notification

JOB_TYPE = "cleanup_old_read_notifications"


def run(db: Session, payload: dict) -> None:
    """docs/modules/notifications.md #9 -- read notifications are
    disposable UI state, not business history (that's the audit trail's
    job), so they're purged once past NOTIFICATION_RETENTION_DAYS.
    Unread notifications are never touched here, however old. Naturally
    idempotent -- deleting rows that are already gone is a no-op, so a
    retried/duplicate run does nothing extra
    (docs/modules/background_jobs.md #7)."""
    cutoff = datetime.utcnow() - timedelta(days=settings.NOTIFICATION_RETENTION_DAYS)
    db.query(Notification).filter(Notification.is_read.is_(True), Notification.read_at < cutoff).delete(
        synchronize_session=False
    )


register_job_handler(JOB_TYPE, run)
