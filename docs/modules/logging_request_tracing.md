# JDK Logging + Request Tracing

Simple, structured, production-focused logging. Keep logging, the audit
trail, and monitoring as three separate concerns.

## 1. Application logging

One central logging mechanism for the entire application.

Log:

- `INFO` — important normal events
- `WARN` — unusual but handled conditions
- `ERROR` — failures requiring investigation
- `DEBUG` — development only

Do not allow each module to invent its own logging format.

## 2. Request ID

Every incoming API request gets a unique `request_id`.

```text
Browser
  ↓ request_id: 8f31...
API
  ↓
Service
  ↓
Database / Job
```

The same ID should appear in all logs generated while processing that
request.

## 3. Structured logs

Prefer structured fields rather than large text messages. Minimum
useful fields:

```text
timestamp
level
request_id
user_id
organisation_id
module
action
message
duration_ms
```

Add entity/record ID where useful.

## 4. API request logging

For important API requests record: method, endpoint/route, request ID,
authenticated user, response status, duration, error code (if any).
Don't log complete request/response bodies by default.

## 5. Business event logging

Important business actions should be identifiable:

```text
quotation.approved
invoice.created
payment.recorded
user.deactivated
```

But business audit trail remains separate from technical logs.

- Audit: what happened to business data and who did it.
- Log: what the application/system did while processing it.

## 6. Error logging

On unexpected errors record: request ID, user/context, operation, error
type, safe technical details, stack trace on server only. The user
receives the standard safe error response, not the stack trace.

## 7. Security-sensitive logging

Never log: passwords, password reset tokens, session tokens, API keys,
secrets, full payment credentials, sensitive personal data
unnecessarily. Mask sensitive values when diagnostic logging genuinely
requires them.

## 8. Performance logging

Record request duration. For unusually slow operations, capture enough
information to identify: slow API, slow database query, background
job, external service. Don't log every SQL query in production by
default.

## 9. Background jobs

Every background job should have its own traceable ID and, where
applicable, retain the originating `request_id`.

```text
Request ID: R123
    ↓
Create PDF job: J456
    ↓
PDF generation
    ↓
Email job: J457
```

This lets you follow a user's action through asynchronous processing.

## 10. Log storage

Foundation should define: central log location, rotation, retention
period, production/development separation, access restrictions. Don't
build a complicated log platform initially.

## 11. Basic monitoring hooks

The logging foundation should make it possible to identify: repeated
errors, failed jobs, unusually slow requests, authentication failures,
database connection failures. A full observability platform can come
later if actually required.

## Core rule

Every important operation should be traceable from request →
application processing → background job → result using a request/job
ID, without exposing sensitive data. Keep logging, audit trail, and
monitoring as three separate concerns.

## Implementation approach

See `docs/audit/LOGGING_REQUEST_TRACING_AUDIT.md` for the full verdict:
what already existed (a request ID context variable, a dedicated error
logger, the `audit_events` table as the separate business-audit
concern), what was a genuine gap (no central logging module, no
structured fields, no log line for a successful request, no slow-request
detection, no redaction, and two real propagation bugs found while
wiring `user_id`/`organisation_id` through — a FastAPI sync-dependency
thread-pool boundary that `ContextVar`s don't cross, and a Starlette
`BaseHTTPMiddleware` quirk that could silently drop the completion log
line for a crashed request), and what's deliberately deferred because
no background-job system exists yet in this repo.
