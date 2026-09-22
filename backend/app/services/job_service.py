import json
import logging
import time
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.job_registry import RetryableJobError, get_job_handler, is_registered
from app.core.logging import get_logger, log
from app.core.request_context import get_request_id, set_request_id
from app.models.job import COMPLETED, FAILED, PENDING, RUNNING, Job

logger = get_logger("jobs")


def dispatch(
    db: Session,
    *,
    job_type: str,
    payload: dict | None = None,
    organisation_id: int | None = None,
    idempotency_key: str | None = None,
    scheduled_at: datetime | None = None,
    max_attempts: int | None = None,
) -> Job:
    """Does not commit -- the caller decides the transaction boundary
    (docs/modules/database_transaction_integrity.md #6, same pattern as
    audit_service.log_event): include this in the same transaction as
    the business change it follows from for the atomic outbox case
    (docs/modules/background_jobs.md #8), or commit it alone right after
    for the simpler "just enqueue this" case -- both are one call to
    dispatch() plus one db.commit(), the difference is only what else
    that commit covers.

    A job_type nobody has registered a handler for
    (app.core.job_registry) is refused outright -- accepting it would
    only create a job that can never be processed
    (docs/modules/background_jobs.md #1/#12).

    idempotency_key makes this call itself idempotent: dispatching the
    same key twice always returns the *same* row, whatever its current
    status -- a caller that wants a fresh run uses a new key
    (docs/modules/background_jobs.md #7), e.g. one scoped to the day for
    a daily cleanup job."""
    if not is_registered(job_type):
        raise ValueError(f"No job handler registered for '{job_type}'.")

    if idempotency_key is not None:
        existing = db.query(Job).filter(Job.idempotency_key == idempotency_key).first()
        if existing is not None:
            return existing

    job = Job(
        job_type=job_type,
        status=PENDING,
        payload=json.dumps(payload) if payload is not None else None,
        organisation_id=organisation_id,
        idempotency_key=idempotency_key,
        max_attempts=max_attempts if max_attempts is not None else settings.JOB_MAX_ATTEMPTS,
        scheduled_at=scheduled_at or datetime.utcnow(),
        # So the worker can restore the caller's own request_id into
        # context when it eventually processes this
        # (docs/modules/logging_request_tracing.md #9) -- "-" (the
        # context's own default when nothing set it) is stored as None,
        # not a literal dash, so it reads as "no originating request."
        originating_request_id=None if get_request_id() == "-" else get_request_id(),
    )
    db.add(job)
    db.flush()
    return job


def claim_pending_jobs(db: Session, *, limit: int | None = None) -> list[Job]:
    """The atomic claim (docs/modules/database_transaction_integrity.md
    #7): a conditional UPDATE ... WHERE status='pending' per candidate,
    not a read-then-write -- if another worker claims the same row
    first, this update's rowcount is 0 and the row is simply skipped,
    never double-claimed. Portable to both SQLite and MySQL (this
    project's one supported production database), unlike
    UPDATE ... ORDER BY ... LIMIT ... RETURNING, which MySQL doesn't
    support at all."""
    limit = limit or settings.JOB_WORKER_BATCH_SIZE
    now = datetime.utcnow()
    candidate_ids = [
        job_id
        for (job_id,) in db.query(Job.id)
        .filter(Job.status == PENDING, Job.scheduled_at <= now)
        .order_by(Job.scheduled_at)
        .limit(limit)
        .all()
    ]

    claimed: list[Job] = []
    for job_id in candidate_ids:
        rowcount = (
            db.query(Job)
            .filter(Job.id == job_id, Job.status == PENDING)
            .update({"status": RUNNING, "started_at": now}, synchronize_session=False)
        )
        db.commit()
        if rowcount == 1:
            claimed.append(db.get(Job, job_id))
    return claimed


def complete_job(db: Session, job: Job) -> None:
    job.status = COMPLETED
    job.finished_at = datetime.utcnow()
    db.add(job)
    db.commit()


def fail_job(db: Session, job: Job, *, error_type: str, error_message: str, retryable: bool) -> None:
    """Limited attempts, increasing delay, final FAILED state
    (docs/modules/background_jobs.md #6). error_message is truncated --
    this column is visible to job monitoring, so it holds a short, safe
    summary, never a full exception dump (docs/modules/background_jobs.md
    #12); the full stack trace goes to the structured log instead."""
    now = datetime.utcnow()
    job.attempts += 1
    job.error_type = error_type
    job.error_message = error_message[:500]
    if retryable and job.attempts < job.max_attempts:
        job.status = PENDING
        job.started_at = None
        delay_seconds = settings.JOB_RETRY_BASE_DELAY_SECONDS * (2 ** (job.attempts - 1))
        job.scheduled_at = now + timedelta(seconds=delay_seconds)
    else:
        job.status = FAILED
        job.finished_at = now
    db.add(job)
    db.commit()


def get_job_stats(db: Session) -> dict:
    """docs/modules/background_jobs.md #11's "make these visible" --
    read directly off the jobs table, no separate monitoring store."""
    oldest_pending = (
        db.query(Job.scheduled_at).filter(Job.status == PENDING).order_by(Job.scheduled_at).limit(1).scalar()
    )
    last_completed = (
        db.query(Job.finished_at).filter(Job.status == COMPLETED).order_by(Job.finished_at.desc()).limit(1).scalar()
    )
    return {
        "pending_count": db.query(Job).filter(Job.status == PENDING).count(),
        "running_count": db.query(Job).filter(Job.status == RUNNING).count(),
        "failed_count": db.query(Job).filter(Job.status == FAILED).count(),
        "completed_count": db.query(Job).filter(Job.status == COMPLETED).count(),
        "oldest_pending_scheduled_at": oldest_pending,
        "last_completed_at": last_completed,
    }


def recover_abandoned_jobs(db: Session) -> int:
    """A RUNNING job whose worker never reported back becomes eligible
    for recovery (docs/modules/background_jobs.md #5) -- routed through
    fail_job's own retry/backoff logic rather than a separate recovery
    path, so a job type that reliably crashes its worker still reaches
    FAILED eventually instead of being "recovered" forever."""
    cutoff = datetime.utcnow() - timedelta(minutes=settings.JOB_STALE_RUNNING_MINUTES)
    stale_jobs = db.query(Job).filter(Job.status == RUNNING, Job.started_at < cutoff).all()
    for job in stale_jobs:
        fail_job(
            db,
            job,
            error_type="abandoned",
            error_message="Worker did not report completion within the stale-running window.",
            retryable=True,
        )
    return len(stale_jobs)


def process_one(db: Session, job: Job) -> None:
    """authenticate/authorize don't apply here (this runs out-of-band,
    not behind a request) -- but the rest of #9's boundary does: locate
    the handler, apply it, record the outcome, log with job_id/
    request_id/job_type/status/duration/error (docs/modules/background_jobs.md
    #11)."""
    if job.originating_request_id:
        set_request_id(job.originating_request_id)

    handler = get_job_handler(job.job_type)
    started_at = time.perf_counter()

    if handler is None:
        # Registered at dispatch time (see dispatch()) but since
        # unregistered between then and now (a deploy removed the
        # handler) -- never retryable, since retrying can't make a
        # missing handler appear.
        fail_job(db, job, error_type="unregistered_job_type", error_message=f"No handler for '{job.job_type}'.", retryable=False)
        _log_outcome(job, started_at, error="unregistered_job_type")
        return

    try:
        payload = json.loads(job.payload) if job.payload else {}
        handler(db, payload)
    except RetryableJobError as exc:
        # Discard whatever partial, uncommitted work the handler did
        # before failing -- fail_job()'s own commit must only ever
        # persist the job's FAILED/retry state, never a half-finished
        # side effect alongside it (docs/modules/database_transaction_integrity.md
        # #6: "roll back on failure").
        db.rollback()
        fail_job(db, job, error_type=type(exc).__name__, error_message=str(exc), retryable=True)
        _log_outcome(job, started_at, error=str(exc))
    except Exception as exc:  # noqa: BLE001 -- a job handler's failure must never crash the worker loop
        db.rollback()
        fail_job(db, job, error_type=type(exc).__name__, error_message=str(exc), retryable=False)
        _log_outcome(job, started_at, error=str(exc), exc_info=True)
    else:
        complete_job(db, job)
        _log_outcome(job, started_at, error=None)


def _log_outcome(job: Job, started_at: float, *, error: str | None, exc_info: bool = False) -> None:
    duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
    level = logging.ERROR if error else logging.INFO
    log(
        logger,
        level,
        f"job {job.job_type} -> {job.status}",
        exc_info=exc_info,
        job_id=job.id,
        job_type=job.job_type,
        status=job.status,
        attempts=job.attempts,
        duration_ms=duration_ms,
        error=error,
    )
