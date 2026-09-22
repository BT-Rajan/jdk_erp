from typing import Callable

from sqlalchemy.orm import Session

# The one place a job_type becomes runnable code
# (docs/modules/background_jobs.md #1/#12) -- dispatch() refuses an
# unregistered job_type, and the worker can only ever call a handler
# that was explicitly registered here. There is no API surface that
# lets a caller supply an arbitrary job_type string to execute; every
# call site passes one of these fixed, hardcoded values (#12: "never
# allow users to arbitrarily execute job types"). Handlers take the
# active session, not their own -- job_service.process_one() commits
# the outcome (COMPLETED/FAILED) in the same session, so a handler's own
# writes and that status transition are never split across connections.
JobHandler = Callable[[Session, dict], None]

_registry: dict[str, JobHandler] = {}


class RetryableJobError(Exception):
    """A job handler raises this for a failure worth retrying (a
    temporary email/external-service failure). Any other exception is
    treated as non-retryable -- e.g. invalid business data -- and the
    job goes straight to FAILED (docs/modules/background_jobs.md #6:
    "retry only operations that are safe to retry")."""


def register_job_handler(job_type: str, handler: JobHandler) -> None:
    _registry[job_type] = handler


def get_job_handler(job_type: str) -> JobHandler | None:
    return _registry.get(job_type)


def is_registered(job_type: str) -> bool:
    return job_type in _registry
