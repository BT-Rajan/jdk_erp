from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config import settings
from app.core.database import Base
from app.models.mixins import TimestampMixin

# Fixed set (docs/modules/background_jobs.md #4) -- plain strings, not a
# DB enum, for the same MySQL/SQLite portability reason every other
# fixed-set column in this project (permissions.scope, teams.is_active's
# sibling audit_events.result, ...) uses a string, not a dialect-specific
# enum type. RETRY_WAIT isn't a separate state -- a retry-eligible job
# goes back to PENDING with scheduled_at pushed forward, per the
# module's own "optionally RETRY_WAIT if retries are implemented
# separately" -- they aren't; PENDING already carries scheduled_at.
PENDING = "pending"
RUNNING = "running"
COMPLETED = "completed"
FAILED = "failed"


class Job(Base, TimestampMixin):
    """One row per background job (docs/modules/background_jobs.md #3).
    payload is a small JSON string -- a reference to the business record
    (an id, not a copy of it), per the module's own guidance. finished_at
    covers both "completed time" and "failed time" from the spec's list:
    status already disambiguates which one it means, so two mostly-empty
    nullable columns would be redundant (docs/modules/database_transaction_integrity.md
    #1's "no unnecessary columns" in spirit). Not organisation-scoped via
    OrganisationScopedMixin -- some jobs are system-level (a cleanup
    sweep) rather than belonging to one organisation, so organisation_id
    is optional here, unlike every business table."""

    __tablename__ = "jobs"
    __table_args__ = (
        # The exact shape of claim_pending_jobs()'s query -- eligible
        # jobs, oldest-scheduled first (docs/modules/background_jobs.md #5/#9).
        Index("ix_jobs_status_scheduled_at", "status", "scheduled_at"),
        Index("ix_jobs_job_type", "job_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    job_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=PENDING)
    payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    organisation_id: Mapped[int | None] = mapped_column(
        ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    # Optional caller-supplied de-duplication key (docs/modules/background_jobs.md
    # #7) -- e.g. "cleanup_expired_refresh_tokens:2026-09-22". Unique
    # when set; nullable so most jobs (no idempotency concern) don't
    # need one. dispatch() returns the existing row instead of creating
    # a duplicate when a caller reuses a key still PENDING/RUNNING.
    idempotency_key: Mapped[str | None] = mapped_column(String(150), unique=True, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=settings.JOB_MAX_ATTEMPTS)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Short, safe code + a truncated message -- never the raw exception
    # text or a stack trace (docs/modules/background_jobs.md #12,
    # "failed-job details must not expose secrets"); the full trace goes
    # to the structured log via exc_info=True, not this row.
    error_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # The request that caused this job to be dispatched, if any --
    # restored into context when the worker processes it
    # (docs/modules/logging_request_tracing.md #9), so the originating
    # request stays traceable through async processing.
    originating_request_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
