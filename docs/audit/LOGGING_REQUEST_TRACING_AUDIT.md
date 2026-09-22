# Logging + Request Tracing Audit

Verdict on `docs/modules/logging_request_tracing.md` against the
existing code: `app/core/request_context.py`, `app/core/error_handlers.py`,
`app/core/request_id_middleware.py`, `app/main.py`, and every
service/router. No background-job system exists in this repo, so
section 9 has no caller yet.

## Already present

- **A per-request correlation ID.** `app/core/request_context.py` +
  `RequestIDMiddleware` already generated a `request_id`, attached it to
  `request.state`, echoed it in the `X-Request-ID` response header, and
  included it in the error envelope's `request_id` field
  (`docs/modules/api_error_handling.md`). This module extends the same
  mechanism rather than replacing it.
- **A dedicated error logger**, not print statements or an unconfigured
  root logger. `app/core/error_handlers.py` already logged every error
  path with the request method/path/status/code.
- **Business audit trail already separate from technical logs**
  (#5's own required distinction). `audit_events`
  (`docs/modules/audit_trail.md`) records *what happened to business
  data and who did it*; nothing in this codebase conflates the two
  concerns, and this phase doesn't change that boundary.
- **No sensitive value ever reached a log call.** Verified directly:
  `decode_token` raises a fixed `"Invalid or expired token."` message,
  never embedding the raw token; the validation-error handler logs only
  field *names* and canned/validator messages, never `error["input"]`
  (the actual submitted value, which could be a password). This phase
  adds redaction as defense in depth on top of an already-clean baseline,
  not as a fix for an active leak.

## Genuine gaps found and fixed

1. **No central logging module.** Log format/handler setup lived inline
   inside `error_handlers.py`'s `register_exception_handlers`, callable
   from nowhere else — the next module to add a log line would have had
   to invent its own handler (exactly #1's "do not allow each module to
   invent its own logging format"). Added `app/core/logging.py`:
   `configure_logging()`/`get_logger()` (one handler, one formatter, one
   level, set once), `log()` (the one structured-logging entry point),
   and `redact()`.
2. **No structured fields — plain `%s`-interpolated text.** Every log
   line was a hand-built string; `user_id`, `organisation_id`,
   `duration_ms`, and `action` never existed as fields anywhere. Replaced
   with one JSON-lines formatter (`_StructuredFormatter`) that always
   emits `timestamp`/`level`/`request_id`/`user_id`/`organisation_id`/
   `module`/`message` plus whatever structured extras the call site
   passes (`docs/modules/logging_request_tracing.md #3`).
3. **No log line for a normal, successful request at all.** Only error
   paths were ever logged — #4's "for important API requests record
   method/route/request ID/user/status/duration/error code" had no
   implementation for the success path. Added `RequestLoggingMiddleware`:
   one line per completed request, covering both outcomes.
4. **No slow-request detection.** #8's "capture enough information to
   identify a slow API" had nothing behind it. `RequestLoggingMiddleware`
   now logs at `WARNING` when `duration_ms` exceeds the new
   `SLOW_REQUEST_THRESHOLD_MS` setting (default 1000ms).
5. **No redaction mechanism.** #7's "never log passwords/tokens/secrets"
   was upheld only by every call site remembering not to — no safety net
   existed for a future mistake. Added `redact()`, applied automatically
   to every structured field `log()` receives.
6. **`user_id`/`organisation_id` weren't available to logging code at
   all.** Extended `request_context.py` with `set_user_context`/
   `get_user_id`/`get_organisation_id`, set once identity resolves
   (`app.api.deps.get_current_user`).
7. **A real propagation bug found while wiring #6 in:** FastAPI runs
   every synchronous dependency (`get_current_user`, `require_admin`)
   and every synchronous route handler in a worker thread
   (`anyio.to_thread.run_sync`, via `run_in_threadpool`). A `ContextVar`
   mutation made inside that thread's copied context does **not**
   propagate back to the caller — proven directly: an authenticated
   request that failed `require_admin`'s check logged `user_id: null` in
   the error handler's own log line, even though `get_current_user` had
   already run and set the ContextVar moments earlier in the same
   request. `request.state` is a plain shared object, not a per-thread
   copy, so it's the one thing that actually crosses this boundary (the
   same reason `error_code` propagation already worked). Fixed by also
   setting `request.state.user_id`/`organisation_id` in
   `get_current_user`, and having `error_handlers.py` and
   `RequestLoggingMiddleware` read from `request.state`, not the
   ContextVar, for these two fields specifically. `request_id` itself is
   unaffected: it's set in the outermost middleware *before* any
   thread/task is spawned, so every descendant correctly inherits it —
   verified by a direct test asserting the same `request_id` appears in
   both the error-handler log line and the request-completion log line
   for one request, and matches the response's own header and JSON body.
8. **A second real bug found while testing #7's fix:** when a
   downstream exception is converted to a response by a registered
   exception handler, that conversion does not reliably survive back
   through an *intermediate* `BaseHTTPMiddleware`'s own `call_next()` —
   a documented Starlette quirk when several such middlewares are
   stacked (as here: `RequestIDMiddleware`, `RequestLoggingMiddleware`,
   `SecurityHeadersMiddleware`). The raw exception re-propagates through
   each one instead, only actually becoming a response at Starlette's
   outermost `ServerErrorMiddleware`. Unhandled, this silently skipped
   `RequestLoggingMiddleware`'s own completion log line for exactly the
   crash requests #6/#11 care about most. Fixed by wrapping `call_next()`
   in `try/except`, logging the completion line (status 500, with a
   stack trace) before re-raising unchanged so the real response-building
   is untouched. A dedicated test forces a 500 and asserts the
   completion line still appears at `ERROR`.

## Reviewed, not changed

- **Log storage/rotation/retention (#10).** This app logs structured
  JSON lines to stdout via a `StreamHandler`. Rotation, retention, and
  production/development separation are the deploying platform's job
  (Docker/Kubernetes log driver, systemd/journald, or a cloud log
  service), not application code — building a file-rotation system here
  would be exactly the "complicated log platform" #10 says not to build.
  `LOG_LEVEL` (default `INFO`) is the one production/development
  separation this app owns directly: set `LOG_LEVEL=DEBUG` locally, never
  in production.
- **Basic monitoring hooks (#11).** Not a dashboard — a consequence of
  #1-#8 already being true. Structured JSON with `level`/`error_code`/
  `duration_ms`/`action` is greppable/alertable for repeated errors,
  slow requests, and auth failures (`error_code=AUTHENTICATION_ERROR`)
  by any log aggregator, without building one here. Database connection
  failures already surface as `SQLAlchemyError` at `ERROR` with a stack
  trace, unchanged by this phase.

## Deliberately not built now

**Background jobs (#9).** No job/queue system exists anywhere in this
repo (no Celery, RQ, APScheduler, or equivalent dependency). The
mechanism a future one should reuse already exists: capture
`get_request_id()` when enqueueing a job, and call `set_request_id()`
(or a small job-scoped equivalent) when a worker picks it up, so the
originating request stays traceable through the job the same way it
already does through the rest of a single request. No job-runner is
invented here to have a caller.

## What's added

| Area | File |
| --- | --- |
| Central logging (config, formatter, redaction) | `app/core/logging.py` |
| User/organisation identity context | `app/core/request_context.py` |
| Set identity on login/every authenticated request | `app/api/deps.py` |
| Request-completion + slow-request + crash logging | `app/core/request_logging_middleware.py` |
| Structured error logging, `request.state.error_code` | `app/core/error_handlers.py` |
| `LOG_LEVEL`, `SLOW_REQUEST_THRESHOLD_MS` settings | `app/core/config.py` |
| Wiring | `app/main.py` |
| Tests | `backend/tests/test_logging.py` |
