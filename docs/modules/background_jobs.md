# JDK Background Jobs

One simple, reliable background-job mechanism for work that should not
block a user request. Database-backed initially, with safe retries,
idempotency, recovery, and clear status.

## 1. Job mechanism

One common service: `dispatch(job)`, `process(job)`, `retry(job)`,
`fail(job)`. Modules create jobs; they do not create their own queue
systems.

## 2. Good candidates

Use background jobs for: email sending, PDF generation, large exports,
file processing, scheduled backups, cleanup/maintenance, other
genuinely long-running operations. Do not move normal CRUD operations
into jobs.

## 3. Job record

Minimum: job ID, job type, status, payload/reference, attempts,
scheduled time, started time, completed/failed time, error information,
created time. Prefer storing a reference to the business record, rather
than copying large business data into the job payload.

## 4. Job states

Keep it simple: `PENDING`, `RUNNING`, `COMPLETED`, `FAILED`.
Optionally `RETRY_WAIT` if retries are implemented separately.

## 5. Reliable processing

A job must not disappear if the worker crashes. Use a database-backed
queue initially if it is sufficient for the application.

```text
Create job
   ↓
PENDING
   ↓
Worker claims job
   ↓
RUNNING
   ↓
COMPLETED
```

If the worker dies, an abandoned `RUNNING` job must eventually become
eligible for recovery.

## 6. Retry

Retry only operations that are safe to retry.

- temporary email failure → retry
- temporary external service failure → retry
- invalid business data → don't blindly retry

Use: limited attempts, increasing delay, final `FAILED` state.

## 7. Idempotency

A retry must not duplicate the business result. For example, an email
job may safely retry without creating two invoices. For jobs that cause
external side effects, maintain an appropriate idempotency/reference
mechanism.

## 8. Transaction boundary

Important:

```text
Business transaction
      ↓
COMMIT
      ↓
Create/dispatch background job
      ↓
Worker performs long-running work
```

Don't hold a database transaction open while a worker sends email,
generates a large PDF, etc. For cases where database change +
guaranteed job creation must be atomic, use a simple transactional
job/outbox pattern rather than relying on timing.

## 9. Worker

One worker mechanism initially: continuously checks/claims pending
jobs, processes one or a controlled number at a time, records
success/failure, releases/retries failed jobs, stops cleanly during
deployment. No microservice required.

## 10. Scheduling

Support simple scheduled jobs: daily backup, nightly cleanup, periodic
maintenance. Use the existing server scheduler/cron to enqueue jobs
rather than building a scheduler framework.

## 11. Monitoring

Make these visible: pending jobs, running jobs, failed jobs, retry
count, oldest pending job, last successful execution.

Logging should include: `job_id`, `request_id` (when applicable),
`job_type`, `status`, `duration`, `error`.

## 12. Security

- Job payloads must not contain secrets unnecessarily.
- Worker runs with minimum required privileges.
- Validate job data before processing.
- Never allow users to arbitrarily execute job types.
- Failed-job details must not expose secrets.

## Core rule

One reliable background-job system, database-backed initially, with
safe retries, idempotency, recovery, and clear status.

## Don't build

Kafka, RabbitMQ unless actual scale requires it, microservices,
distributed job orchestration, complex workflow engine, priority
scheduling system, multiple queue technologies. For this reusable
foundation, database-backed jobs + one worker + cron for scheduling is
enough initially.

## Implementation approach

See `docs/audit/BACKGROUND_JOBS_AUDIT.md` for the full verdict: what
already existed (the request-id context mechanism, structured logging,
the atomic-claim/validate-then-transact patterns from the Database
Integrity module), what was a genuine gap (no job mechanism, registry,
retry/backoff, crash recovery, idempotency, worker, monitoring, or
scheduling entry point -- plus a real transaction-safety bug found while
wiring a handler's own writes into the same session as its job-status
update), and what's deliberately deferred because no real long-running
operation (email sending, PDF generation, ...) exists yet in this repo
beyond the one genuine maintenance job this phase built and registered.
