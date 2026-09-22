"""Dispatches the background job that sends a notification's email
(docs/modules/notifications.md #7) -- kept as its own thin module,
separate from notification_service.py, purely to break the import cycle
with app/jobs/send_notification_email.py (the job handler reads the
Notification row this dispatches for). No business logic lives here.
"""

from sqlalchemy.orm import Session

from app.models.notification import Notification
from app.services import job_service


def dispatch_email(db: Session, notification: Notification) -> None:
    """Does not commit -- part of the same transaction as
    notify()/the caller's own business change (docs/modules/background_jobs.md
    #8: create the job, don't hold a transaction open while it runs)."""
    from app.jobs.send_notification_email import JOB_TYPE

    job_service.dispatch(
        db,
        job_type=JOB_TYPE,
        payload={"notification_id": notification.id},
        organisation_id=notification.organisation_id,
    )
