from datetime import datetime

from sqlalchemy.orm import Session

from app.core.job_registry import register_job_handler
from app.models.refresh_token import RefreshToken

JOB_TYPE = "cleanup_expired_refresh_tokens"


def run(db: Session, payload: dict) -> None:
    """A real maintenance candidate (docs/modules/background_jobs.md #2),
    not a demo job invented to exercise the framework: expired refresh
    tokens have no value once past expires_at -- unlike audit_events,
    they're pure session records
    (docs/modules/database_transaction_integrity.md #2's reasoning for
    their CASCADE delete behaviour already applies here too). Naturally
    idempotent -- deleting rows that are already gone is a no-op, so a
    retried/duplicate run does nothing extra
    (docs/modules/background_jobs.md #7)."""
    db.query(RefreshToken).filter(RefreshToken.expires_at < datetime.utcnow()).delete(synchronize_session=False)


register_job_handler(JOB_TYPE, run)
