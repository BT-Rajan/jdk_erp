import threading
import time

from app.core.database import SessionLocal
from app.core.config import settings
from app.services import job_service


def run_worker(
    *,
    stop_event: threading.Event | None = None,
    max_iterations: int | None = None,
    poll_interval_seconds: float | None = None,
    batch_size: int | None = None,
) -> None:
    """One worker mechanism (docs/modules/background_jobs.md #9):
    continuously claims a controlled batch of pending jobs, processes
    them one at a time, records success/failure, and sleeps when there's
    nothing to do. No microservice, no separate queue technology --
    everything it needs is already in the `jobs` table.

    Stops cleanly during deployment: `stop_event` is checked *between*
    jobs, never mid-job, so an in-progress job always finishes before
    the loop exits (a caller sets the event from a signal handler or a
    test). `max_iterations` is test-only, so a test can run the loop a
    bounded number of times instead of forever."""
    poll_interval_seconds = poll_interval_seconds if poll_interval_seconds is not None else settings.JOB_WORKER_POLL_INTERVAL_SECONDS
    batch_size = batch_size or settings.JOB_WORKER_BATCH_SIZE

    iterations = 0
    while stop_event is None or not stop_event.is_set():
        db = SessionLocal()
        try:
            job_service.recover_abandoned_jobs(db)
            jobs = job_service.claim_pending_jobs(db, limit=batch_size)
            for job in jobs:
                if stop_event is not None and stop_event.is_set():
                    break
                job_service.process_one(db, job)
        finally:
            db.close()

        iterations += 1
        if max_iterations is not None and iterations >= max_iterations:
            return
        if not jobs:
            if stop_event is not None:
                stop_event.wait(poll_interval_seconds)
            else:
                time.sleep(poll_interval_seconds)
