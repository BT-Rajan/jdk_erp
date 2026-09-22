"""Enqueue the daily expired-refresh-token cleanup job
(docs/modules/background_jobs.md #10: "use the existing server
scheduler/cron to enqueue jobs rather than building a scheduler
framework") -- point the deployment's own cron at this, once a day:

    0 3 * * * cd /path/to/backend && .venv/bin/python -m scripts.enqueue_cleanup

Safe to run more than once on the same day: the idempotency key is
scoped to today's date, so a duplicate cron fire (or a manual re-run)
returns the same job instead of creating a second one
(docs/modules/background_jobs.md #7).
"""
import sys
from datetime import date
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

import app.jobs  # noqa: F401 -- registers the handler dispatch() checks for
from app.core.database import SessionLocal
from app.jobs.cleanup_expired_refresh_tokens import JOB_TYPE
from app.services import job_service


def main() -> None:
    db = SessionLocal()
    try:
        job = job_service.dispatch(db, job_type=JOB_TYPE, idempotency_key=f"{JOB_TYPE}:{date.today().isoformat()}")
        db.commit()
        print(f"Enqueued job {job.id} ({job.status}).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
