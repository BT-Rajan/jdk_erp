# Common API & Error Handling Audit — `jdk_clean`

Phase 0 audit of API error handling, per [`../ROADMAP.md`](../ROADMAP.md)
and the spec in [`../modules/api_error_handling.md`](../modules/api_error_handling.md).

## Verdict

**Reuse the architecture almost entirely — this is the strongest, most
directly reusable design found in `jdk_clean` so far.** A five-class
`AppError` hierarchy, one global exception-handler chokepoint covering
`AppError`/validation/DB errors/anything unexpected, and a per-error
support code that lets a user quote a short string to support while the
full diagnostic stays server-side. Close it against the two real gaps
the spec explicitly calls out (a structured `fields` array, and a
success/error envelope), and fix the handful of concrete leak risks
found.

## What's reused, almost as-is

- **The exception hierarchy** (`app/core/exceptions.py:12-43`):
  `AppError` base with a fixed HTTP status baked into each subclass —
  `NotFoundError` (404), `ValidationAppError` (422), `ConflictError`
  (409), `AuthError` (401), `PermissionError_` (403). This project adds
  a `BusinessRuleError` (400) the legacy app didn't have as its own
  class (it folded business-rule rejections into `ConflictError`/
  `ValidationAppError` instead — workable, but this spec names
  `BUSINESS_RULE_ERROR` as its own category, so it gets its own class)
  and a `RateLimitedError` (429, `jdk_clean` had no rate limiting at
  all). Every class also gains an explicit `code` string
  (`"NOT_FOUND"`, etc.) — `jdk_clean` only ever had the HTTP status,
  no separate machine-readable code the client could switch on.
- **One global chokepoint, not per-endpoint handling.**
  `register_exception_handlers()` (`app/core/exceptions.py:73-123`)
  funnels `AppError`, `RequestValidationError`, `IntegrityError`,
  `SQLAlchemyError`, and generic `Exception` through one response
  builder. This project keeps that shape exactly — one
  `register_exception_handlers(app)` call, one internal response
  builder, no per-module error handling.
- **DB errors never reach the client raw.** Both `IntegrityError` and
  generic `SQLAlchemyError` are caught globally and turned into a fixed
  safe sentence, with the real exception logged via `exc_info=True`
  server-side only (`app/core/exceptions.py:98-114`). Confirmed: no
  call site anywhere in `jdk_clean` lets a DB error's `str()` reach a
  response. Kept exactly.
- **A quotable reference code, logged alongside the full diagnostic.**
  `generate_support_code()` (`app/core/exceptions.py:46-54`) — a short
  code shown to the user and grep-able in the server log next to the
  real error. This project generalizes it slightly: one id per
  *request* (set by middleware, in `app/core/request_context.py`)
  rather than freshly generated per error, so it's available even for
  logging non-error events later, but the concept and the "show short
  code, log full detail" mechanics are the same.
- **404, not 403, for a scoped-out record.** `app/api/sales_scope_guard.py`'s
  documented anti-enumeration pattern (a salesman probing another
  salesman's order 404s, not 403s, so record ids can't even be probed)
  matches this project's own established pattern from every prior
  module (`ORGANISATION_AUDIT.md`, `USERS_AUDIT.md`, `TEAMS_AUDIT.md` —
  cross-boundary lookups already return 404 everywhere in this
  project). Confirms the existing convention rather than changing it.
- **Neutral 403/404 wording as a deliberate design choice, not an
  accident** — `PermissionError_()`'s default message
  (`"You do not have permission to do this."`) never names the page,
  department, or rule involved. Kept.
- **A shared "assert transition allowed" primitive**
  (`app/core/workflow.py:54-71`), replacing what the codebase's own
  history shows were five near-duplicate hand-rolled implementations
  across order/quotation/purchase-order/production/feasibility
  services. Worth reusing the *pattern* — a shared status-transition
  assertion helper — once a module with a status workflow exists
  (Phase 2+); not implemented now since nothing has states to transition
  yet.

## What's fixed rather than reused

- **Only the first validation error is ever surfaced**
  (`exc.errors()[0]`, `app/core/exceptions.py:90`) — a payload with
  three invalid fields tells the client about exactly one. This
  project's validation handler walks the full `exc.errors()` list and
  returns every field's message in a `fields` dict, closing this gap
  directly (§7's "return field-level errors" requirement).
- **No success/error envelope consistency** — `jdk_clean` has three
  different success shapes (a bare resource, a bare paginated list, and
  a bespoke per-row bulk-import result) and confirmed one endpoint
  (`app/api/reports.py:42`, a raw `HTTPException`) that leaks FastAPI's
  own default `{"detail": ...}` shape instead of the app's `{"error":
  ...}` convention. This project closes the *error*-shape leak by also
  registering a handler for Starlette's base `HTTPException` (so even a
  future accidental `raise HTTPException(...)` — or a framework-internal
  404 for an unmatched route — still comes back through the standard
  envelope, not FastAPI's default). It does **not** introduce a
  `{success: true, data: ...}` wrapper around every success response —
  see the implementation-approach section below for why.
- **A caught exception's raw text reaching a client message** — three
  concrete instances found (`doc_converter.py:76-77` interpolating raw
  subprocess `stderr`, `products.py:87`'s dead-but-live-landmine
  `str(exc)` fallback, `whatsapp_account_service.py`/`sms_account_service.py`
  forwarding a caught `ValueError`'s message verbatim). Nothing in this
  project's own code does this today (confirmed by review of the
  current codebase), and the rule — never interpolate a caught
  exception's `str()` or third-party output into a client message,
  translate to a fixed sentence and log the raw detail instead — is
  written into `CONTRIBUTING.md` for every future module, since that's
  exactly the drift the legacy codebase shows happens without it.
- **No guaranteed destination for error logs** — `jdk_clean`'s
  `"app"` logger has no explicit handler configured anywhere in-repo,
  unlike its deliberately dedicated `request_logging.py`. This
  project's error logger (`jdk.errors`) is given an explicit handler at
  startup rather than relying on ambient root-logger/process-manager
  behaviour.
- **Rate limiting was folded into `AuthError`/401** — `jdk_clean` had no
  rate limiting to categorize in the first place. This project's login
  lockout (already built in the authentication phase) is recategorized
  from `AuthError`/401 to the new `RateLimitedError`/429, matching the
  spec's own `RATE_LIMITED` category precisely.

## Implementation approach

**No success envelope.** The spec's §13 shape is explicitly offered
as a concept, with the instruction to "follow the existing JDK stack
after audit; don't impose a new API framework unnecessarily." Every
endpoint built so far (Organisation, Users, Teams, Permissions, Audit
Trail) returns its resource directly with an idiomatic HTTP status —
the same pattern `jdk_clean` itself settled on. Wrapping every success
response in `{success: true, data: ...}` now would be a purely
cosmetic, unrequested breaking change touching every existing schema
and all 99 tests, for zero safety or leakage benefit — the spec's actual
risk is about *errors* leaking internals, not about success responses
needing a wrapper. The **error** side gets the full envelope described
in §13, applied uniformly through the global handlers; success stays as
it is.
