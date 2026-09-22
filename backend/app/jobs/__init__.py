"""Importing this package registers every known job handler
(docs/modules/background_jobs.md #1) -- app/main.py imports it once at
startup, the same way app/models/__init__.py registers every model on
Base.metadata. A new job type is a new module here plus one line below,
never a change to app/core/job_registry.py or app/services/job_service.py."""
from app.jobs import cleanup_expired_refresh_tokens  # noqa: F401
