# Background Jobs Audit

Verdict on `docs/modules/background_jobs.md` against the existing code.
No long-running operation (email sending, PDF generation, large export)
exists yet in this repo, so this audit covers the job mechanism itself
plus the one genuine maintenance candidate it was built against.

## Already present, reused as-is

- **The request-id context mechanism.** `app/core/request_context.py`
  (built for `docs/modules/logging_request_tracing.md`) already had
  exactly the shape #9's "retain the originating request_id" needs.
  `dispatch()` captures `get_request_id()` at enqueue time onto
  `Job.originating_request_id`; `process_one()` restores it via
  `set_request_id()` before running the handler, so a job's log lines
  correlate back to the request that caused it -- the exact promise the
  Logging audit made when it deferred this ("the mechanism it should
  reuse already exists").
- **Structured logging.** `app/core/logging.py`'s `get_logger`/`log()`
  is used as-is for every job outcome line -- `job_id`, `job_type`,
  `status`, `attempts`, `duration_ms`, `error` (#11), no new logging
  setup invented.
- **The atomic-claim pattern.** `docs/modules/database_transaction_integrity.md
  #7`'s "prefer database-level atomic operations... an atomic/locked
  update" is exactly what `claim_pending_jobs()` needed: a conditional
  `UPDATE ... WHERE status='pending'` per candidate row, not a
  read-then-write. Portable to MySQL (this project's one supported
  production database), unlike `UPDATE ... ORDER BY ... LIMIT ...
  RETURNING`, which MySQL doesn't support.
- **Validate-then-transact, one commit per operation.** `dispatch()`
  doesn't commit (same pattern as `audit_service.log_event`) --
  the caller decides the transaction boundary, supporting both the
  simple case (dispatch, then commit alone) and the outbox case
  (dispatch inside the same transaction as the business change it
  follows from) with the same function.
- **Explicit `ON DELETE`.** `jobs.organisation_id` uses `RESTRICT`,
  consistent with every other organisation-scoped column in this
  project.

## Genuine gaps filled

1. **No job mechanism existed at all.** Added `app/services/job_service.py`
   (`dispatch`/`claim_pending_jobs`/`complete_job`/`fail_job`/
   `recover_abandoned_jobs`/`get_job_stats`) and `app/models/job.py`
   (#1/#3).
2. **No job-type registry.** #12's "never allow users to arbitrarily
   execute job types" had nothing enforcing it. Added
   `app/core/job_registry.py`: `dispatch()` refuses a `job_type` with no
   registered handler, and there is no API endpoint anywhere that lets a
   caller supply an arbitrary `job_type` string -- every call site
   passes a fixed, hardcoded value. `app/jobs/__init__.py` registers
   every known handler at import time (mirroring
   `app/models/__init__.py`'s own pattern for models).
3. **No retry/backoff.** Added to `fail_job()`: a job handler opts into
   retry by raising `RetryableJobError` specifically (#6 -- "retry only
   operations that are safe to retry"; any other exception is
   non-retryable by default, a safer default than retrying everything).
   Exponential backoff (`JOB_RETRY_BASE_DELAY_SECONDS * 2^(attempts-1)`)
   pushes `scheduled_at` forward; exhausting `max_attempts` reaches
   `FAILED`.
4. **No crash recovery.** Added `recover_abandoned_jobs()`: a `RUNNING`
   job whose `started_at` is older than `JOB_STALE_RUNNING_MINUTES`
   (#5) is routed through the same `fail_job()` retry/backoff logic --
   not a separate recovery path -- so a job type that reliably crashes
   its worker still reaches `FAILED` eventually instead of being
   "recovered" forever.
5. **No idempotency mechanism.** Added `idempotency_key` (unique,
   nullable): `dispatch()` returns the existing row for a repeat key
   instead of creating a duplicate (#7), verified directly with the
   real handler (`cleanup_expired_refresh_tokens` run twice back to
   back deletes nothing extra the second time and doesn't error).
6. **A real transaction-safety gap found while wiring `process_one()`
   in:** a job handler's own database writes and `fail_job()`'s status
   update share one session. Without an explicit `db.rollback()` before
   `fail_job()` on failure, a handler that wrote something and *then*
   raised would have that partial write silently committed alongside
   the job's `FAILED` status the next time anything committed on that
   session -- a real one-transaction violation
   (`docs/modules/database_transaction_integrity.md #6`: "roll back on
   failure"). Fixed, and covered directly by a test that has a handler
   write a row, then fail, and asserts the row never persisted.
7. **No worker.** Added `app/services/job_worker.py`: claims a batch,
   recovers abandoned jobs first, processes one at a time, sleeps when
   idle, and checks a `stop_event` *between* jobs (never mid-job) so an
   in-progress job always finishes before a clean shutdown (#9).
   `scripts/run_worker.py` runs it as one long-lived process with
   `SIGINT`/`SIGTERM` wired to the same `stop_event`.
8. **No monitoring surface.** #11's "make these visible" had nothing to
   look at. Added `GET /api/jobs/stats` (admin-gated): pending/running/
   failed/completed counts, oldest-pending age, last-success time --
   read directly off the `jobs` table, no separate store.
9. **No scheduling entry point.** #10 explicitly says to use the
   deployment's own cron rather than build a scheduler. Added
   `scripts/enqueue_cleanup.py`, a plain script a cron line calls once a
   day; its own idempotency key (scoped to the date) makes a duplicate
   cron fire harmless.

## The one real job type, not a fabricated demo

`cleanup_expired_refresh_tokens` (`app/jobs/cleanup_expired_refresh_tokens.py`)
was chosen deliberately over inventing a fake job to exercise the
framework: #2 lists "cleanup/maintenance" as a good candidate by name,
and `RefreshToken` rows already have no value once past `expires_at`
(the same reasoning `docs/audit/DATABASE_TRANSACTION_INTEGRITY_AUDIT.md`
gave for their `CASCADE`-on-user-delete behaviour applies here too).
It's naturally idempotent -- deleting rows that are already gone is a
no-op -- so it doubles as this module's own idempotency proof rather
than needing a separate synthetic one.

## Reviewed, not built

- **Job payloads and secrets (#12).** `dispatch()` stores whatever
  `payload` dict a caller passes, JSON-serialized, with no special
  inspection -- the same trust boundary `audit_service.log_event`'s
  `details` field already has. The guidance ("must not contain secrets
  unnecessarily") is a caller discipline, documented in
  `app/services/job_service.py`'s own docstring and the module doc,
  not something the framework can safely auto-redact without knowing
  a job type's actual shape.
- **"Worker runs with minimum required privileges" (#12).** A
  deployment/process-configuration concern (which OS user, which DB
  credentials `scripts/run_worker.py` runs as), not application code.
  Documented in the backend README as an operational requirement.
- **A generic `POST /api/jobs` dispatch endpoint.** Deliberately not
  built -- that would be exactly the "let users arbitrarily execute job
  types" #12 forbids. Every real dispatch call site is Python code that
  passes a fixed `job_type` constant; there is no way for an HTTP client
  to choose one.

## Deliberately not built now

No email sending, PDF generation, or large export exists yet in this
repo, so there's no second real job type to register beyond the
maintenance one above -- inventing one would be building a feature to
have a caller, not the other way around. The mechanism (registry,
retry, idempotency, recovery, the transactional-outbox pattern via
`dispatch()`'s no-commit contract) is ready for whichever module needs
it first.

## What's added

| Area | File |
| --- | --- |
| Job model | `app/models/job.py`, migration `0014` |
| Job-type registry, `RetryableJobError` | `app/core/job_registry.py` |
| dispatch/claim/complete/fail/recover/stats | `app/services/job_service.py` |
| Worker loop | `app/services/job_worker.py` |
| The one real job handler | `app/jobs/cleanup_expired_refresh_tokens.py`, `app/jobs/__init__.py` |
| Monitoring endpoint | `app/api/jobs.py`, `app/schemas/job.py` |
| Worker process, cron entry point | `backend/scripts/run_worker.py`, `backend/scripts/enqueue_cleanup.py` |
| Settings | `app/core/config.py` |
| Tests | `backend/tests/test_jobs.py` |
