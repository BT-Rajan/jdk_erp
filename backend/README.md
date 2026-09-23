# Backend

Server-side application: API, authentication, authorization (RBAC),
business rules and database access. Follow
[`../docs/ENGINEERING_PRINCIPLES.md`](../docs/ENGINEERING_PRINCIPLES.md)
for every module added here.

## Stack

- **FastAPI** + **SQLAlchemy 2.x** (ORM), Python 3.11+.
- **SQLite by default** for local dev and tests (zero setup); **MySQL**
  (`mysql+pymysql://...`) in staging/production via `DATABASE_URL`. This
  keeps the app's logic identical across environments — only the DB
  connection string changes.
- **Alembic** for schema migrations. Models under `app/models/` are the
  single source of truth for the schema; migrations under `migrations/`
  version it. (This replaces `jdk_clean`'s hand-authored `schema.sql` +
  custom migration runner with a standard tool, so there's one schema
  definition instead of two kept in sync by hand.)
- **bcrypt** (via passlib) for password hashing, **JWT** (via python-jose)
  for a stateless access token paired with a server-tracked, rotating,
  revocable refresh token.

This stack is a direct continuation of the audit's verdict in
[`../docs/audit/AUTHENTICATION_AUDIT.md`](../docs/audit/AUTHENTICATION_AUDIT.md):
reuse and harden the design `jdk_clean` already had, not adopt something
new.

## Implemented so far

- **Authentication** (`app/api/auth.py`, `app/services/auth_service.py`) —
  login, logout, token refresh (rotating), self-service password change,
  current-user resolution. Matches
  [`../docs/modules/authentication.md`](../docs/modules/authentication.md).
  Deliberately **excludes** roles, permissions, and admin-initiated
  password reset — those belong to the RBAC/user-management layer, built
  next, on top of this one.
- **Organisation** (`app/api/organisations.py`, `app/models/organisation.py`) —
  the top-level data/access boundary: full organisation record (name,
  code, contact, address, currency, timezone, active flag), `GET
  /api/organisations/me`, and deactivation enforced in both login and
  current-user resolution (an inactive organisation blocks new logins
  *and* kills already-issued tokens on their next use). Matches
  [`../docs/modules/organisation.md`](../docs/modules/organisation.md).
  Deliberately **excludes** an admin API to create/edit/deactivate
  organisations — that needs a Super Admin role RBAC hasn't defined yet.
  Every future organisation-owned table (customers, products, ...) mixes
  in `OrganisationScopedMixin` (`app/models/mixins.py`) instead of
  redeclaring the FK + index.
- **Users** (`app/api/users.py`) — an organisation-scoped user directory:
  `GET /api/users` (paginated, active-only by default, filterable by
  `team_id`) and `GET /api/users/{id}`, both scoped to the caller's own
  organisation (a cross-organisation lookup returns 404, never confirming
  another organisation's user exists); `POST /api/users` (admin-gated) to
  create a user with a role and optional initial team assignment, and
  `PATCH /api/users/{id}/role` / `PATCH /api/users/{id}/status`
  (admin-gated) to change role or activate/deactivate. Matches
  [`../docs/modules/users.md`](../docs/modules/users.md). Still
  **excludes** editing an existing user's name/email — nothing has asked
  for that yet. `UserOut` (`app/schemas/user.py`) is the one public-safe
  user shape, shared between `/api/auth/me` and the directory endpoints,
  carrying `role` and `team_ids`.
- **Teams** (`app/api/teams.py`, `app/models/team.py`) — organisational
  grouping only, no permission data: `GET /api/teams`, `GET
  /api/teams/{id}`, and `GET /api/users?team_id=...` to view a team's
  members (reusing the existing directory endpoint rather than adding a
  new one). Team name and code are unique *within* an organisation (not
  globally — teams aren't a login identifier, so there's no
  disambiguation problem the way there was for usernames). Matches
  [`../docs/modules/teams.md`](../docs/modules/teams.md). Still
  **excludes** create/edit/deactivate for the team itself. Also
  deliberately excludes two things `jdk_clean`'s equivalent
  (`Department`) had: a department-to-page permission matrix (that's
  RBAC's job, not a team's) and a `manager_id` reporting-line column (a
  manager's scope should be `role = Manager` + `team`, not a separate
  hierarchy) — see [`../docs/audit/TEAMS_AUDIT.md`](../docs/audit/TEAMS_AUDIT.md).
- **Roles & RBAC** (`app/core/roles.py`, `app/models/user_team.py`) —
  `User.role` (`super_admin`/`admin`/`manager`/`team_member`, a plain
  column, not a `roles` table — a small fixed set, not organisation
  configuration), and team membership corrected to many-to-many
  (`user_teams`, replacing the earlier one-`team_id`-column design)
  before any role-gated endpoint was built against it. `POST
  /api/teams/{team_id}/members`, `DELETE
  /api/teams/{team_id}/members/{user_id}`, and `PATCH
  /api/users/{user_id}/role` are gated by `require_admin`
  (`app/api/deps.py`) and re-check the organisation boundary. Matches
  [`../docs/modules/roles_rbac.md`](../docs/modules/roles_rbac.md).
  Deliberately **excludes** the `OWN/TEAM/ALL` module-permission engine
  that document also describes — no business module exists yet to
  consult it, so it's specified as a contract for the first one that
  does, not built with no caller.
- **Permissions / Access Scope** (`app/services/authorization_service.py`,
  `app/api/permissions.py`) — the layer that ties the rest together.
  `role_permissions` (role → module/action → scope, the org-wide
  default) and `user_permissions` (per-user override, always wins) as
  two small tables — not one polymorphic table with a nullable
  role/user_id column, since a partial unique index isn't portable to
  MySQL. `module_key`/`action` are free-form lowercase-snake-case
  strings, not a fixed catalog: a future module registers one by writing
  a permission row, not by editing a Python constant (unlike
  `jdk_clean`'s hardcoded `PAGE_KEYS` tuple — see
  [`../docs/audit/PERMISSIONS_AUDIT.md`](../docs/audit/PERMISSIONS_AUDIT.md)).
  `get_effective_scope()`/`can()` are the `can(user, action, resource)`
  concept from the spec, minus the resource argument (nothing to check
  ownership against yet); `get_user_team_ids()` is the one reusable
  "which teams can I see" building block. Management API
  (`PUT`/`DELETE /api/permissions/roles/...`,
  `PUT`/`DELETE /api/permissions/users/{id}/...`) is `require_admin`-gated
  and org-scoped; `GET /api/permissions/me` is self-service. Matches
  [`../docs/modules/permissions.md`](../docs/modules/permissions.md).
  Deliberately **excludes** a generic resource-agnostic query-scoping
  helper (`WHERE team_id IN (...)`) — no concrete table's columns exist
  yet to validate one against; documented as a contract instead.
- **Session / Security hardening** (`app/core/security_headers.py`) — an
  idle timeout on top of the refresh token's existing absolute timeout
  (`SESSION_IDLE_TIMEOUT_MINUTES`, checked/updated at the same point the
  token is already rotated, so it costs no extra query on ordinary
  requests); role changes now also revoke the user's sessions; a new
  `role_changed`/`team_added`/`team_removed` audit trail records who
  performed the action via `AuditEvent.actor_user_id`; centralized
  security-headers middleware (CSP, `X-Content-Type-Options`,
  `X-Frame-Options`, `Referrer-Policy`, conditional HSTS); and an opt-in
  `FORCE_HTTPS` for deployments that terminate TLS themselves. Matches
  [`../docs/modules/session_security.md`](../docs/modules/session_security.md).
  **Keeps the bearer-token transport** rather than switching to a
  cookie-based session as that document's §2 conditionally prefers — no
  frontend exists yet in this repo to have the `localStorage` problem it
  warns about, a bearer token is immune to CSRF by construction (making
  §9 not-applicable rather than something to build), and mobile-app
  compatibility stays open. Full reasoning in
  [`../docs/audit/SESSION_SECURITY_AUDIT.md`](../docs/audit/SESSION_SECURITY_AUDIT.md).
- **Audit Trail** (`app/models/audit_event.py`, `app/services/audit_service.py`,
  `app/api/audit_events.py`) — one unified `audit_events` table for both
  security and business events, generalized in place from the
  session/security phase's security-only `AuthEvent` rather than kept as
  a second, parallel table (the spec's own example mixes a sales
  approval, a role change, and a stock adjustment in one list). One row
  per *event*, not per changed field like `jdk_clean`'s `audit_log` —
  `details` holds a compact "field: old -> new" string via the new
  `audit_service.diff_fields()`/`format_changes()` helpers, which also
  foreclose the diffing-logic duplication `jdk_clean` fell into across
  6+ services (see
  [`../docs/audit/AUDIT_TRAIL_AUDIT.md`](../docs/audit/AUDIT_TRAIL_AUDIT.md)).
  `audit_service.log_event()` never commits — the caller commits the
  audit row in the same transaction as the business change, matching
  `jdk_clean`'s one genuinely good property here (verified by its own
  test that a failed audit write rolls back the business change too).
  `GET /api/audit-events` is `require_admin`-gated, always
  organisation-scoped and paginated, and filters by user, actor, module,
  action, entity, and date range — a real admin-facing audit browser,
  which `jdk_clean` never built (every read there requires already
  knowing a specific record, or asking about yourself). Matches
  [`../docs/modules/audit_trail.md`](../docs/modules/audit_trail.md).
- **Common API & Error Handling** (`app/core/errors.py`,
  `app/core/error_handlers.py`, `app/core/request_context.py`,
  `app/core/request_id_middleware.py`) — a non-negotiable platform rule,
  not a per-module choice: every error response is one standard envelope
  (`{"success": false, "error": {"code", "message", "fields"}, "request_id"}`)
  built from a small, fixed `AppError` hierarchy (`ValidationError`,
  `AuthError`, `AccessDeniedError`, `NotFoundError`, `ConflictError`,
  `BusinessRuleError`, `RateLimitedError`) — no route or service raises a
  raw `fastapi.HTTPException` (see `CONTRIBUTING.md`). Global handlers
  catch every remaining case too (an uncaught `IntegrityError`,
  `SQLAlchemyError`, or any other exception) so nothing but the safe
  envelope ever reaches a client; the full technical detail (stack trace,
  SQL, file paths) is logged server-side only, tagged with a per-request
  correlation id (`X-Request-ID` response header, echoed in the body as
  `request_id`) set once by `RequestIDMiddleware` and readable from
  service-layer logging too via a `ContextVar`. Unlike `jdk_clean`'s
  equivalent, which only ever surfaced `exc.errors()[0]`, request
  validation failures report every invalid field at once in `fields`, so
  a UI can show them all beside their inputs. Matches
  [`../docs/modules/api_error_handling.md`](../docs/modules/api_error_handling.md).
  Reused jdk_clean's `AppError`/global-handler design almost as-is (its
  strongest, most directly reusable pattern of any module audited so
  far), fixing its confirmed gaps and adding an explicit `code` field it
  lacked; see
  [`../docs/audit/API_ERROR_HANDLING_AUDIT.md`](../docs/audit/API_ERROR_HANDLING_AUDIT.md).
  Deliberately **excludes** wrapping success responses in a matching
  envelope — the spec's own §13 says to follow the existing stack rather
  than impose a new API framework, and jdk_clean never had a consistent
  success envelope either; only the error side needed the leak-proofing
  this module is about.

Every gap the audit found has a fix in this implementation:

| Audit finding | Fix |
| --- | --- |
| Hardcoded default JWT secret | `JWT_SECRET_KEY` has no default — app refuses to start without it (`app/core/config.py`) |
| No login rate limiting | Rolling-window lockout by username (`app/services/auth_service.py`, `LOGIN_LOCKOUT_THRESHOLD`/`_WINDOW_MINUTES`) |
| No authentication audit trail | `audit_events` table logs every login success/failure, logout, password change (`app/models/audit_event.py`) |
| Timing/enumeration leaks | Password verification always runs (dummy hash for unknown users); one generic message for bad password / unknown user / inactive account |
| Password policy was length-only | Full complexity check — length, uppercase, digit, special character (`app/core/validation.py`) |
| Vestigial `role` claim in JWT | Not present — the access token carries only `sub`/`org` |
| `users` table missing `organisation_id`/`last_login` | Both present from the start (`app/models/user.py`) |

Deferred, not forgotten (see the audit doc's action items): mobile secure
token storage, unifying frontend/mobile refresh clients, and CLI-script
consolidation — none of these apply yet since no frontend/mobile app
exists in this repo yet.

### Common Validation (docs/modules/common_validation.md)

One authoritative implementation for cross-cutting rules, built ahead of
the Sales/Finance/Products/Materials modules that will consume it
(docs/audit/COMMON_VALIDATION_AUDIT.md):

- **Email** (`app/core/validation.py`): `normalize_email`,
  `validate_email_format` (via the `email_validator` package already used
  by `EmailStr`), `validate_company_email_domain` — the allowed domain is
  `Organisation.email_domain`, per-organisation configuration, not a
  hard-coded constant; `None` means no restriction.
- **Date ranges** (`app/core/validation.py`): `validate_date_range` — the
  one `start <= end` comparison mechanism, same-day valid, only
  `start > end` rejected. Past/future restrictions stay a business rule
  the calling module enforces.
- **ID formats** (`app/core/id_formats.py`): one `IdFormat` shape
  (prefix + digit count), instantiated for Quotation (`QXXXXXX`), Order
  (`OXXXXXX`), User (`XXXXX`), Product (`PRXXXX`), Material (`MXXXX`).
  Owns only the shape — the owning module supplies the next sequence
  number.
- **Currency** (`app/core/currency.py`): `KWD` is the default currency
  (`Organisation.currency`'s default), 3 decimal places (fils) vs. most
  currencies' 2; `round_currency` uses `Decimal`/`ROUND_HALF_UP`, never
  `float`.
- **Timezone** (`app/core/timezone.py`): `Asia/Kuwait`
  (`Organisation.timezone`'s default) is the one place any timestamp is
  converted for display — every stored timestamp stays naive-UTC.
- **QR codes** (`app/core/qr.py`): `validate_qr_url` centralizes the
  domain/HTTPS check (`ALLOWED_QR_DOMAINS` setting) before
  `generate_qr_code` renders a PNG with the standard logo-overlay
  treatment — no module builds its own QR image or invents its own
  branding.

Not built yet, on purpose: no endpoint calls any of this (no
user-creation, Quotation, Order, Product, or Material endpoint exists),
so it's verified standalone (`tests/test_common_validation.py`,
`tests/test_qr.py`) rather than through a request/response test.

### Database + Transaction Integrity (docs/modules/database_transaction_integrity.md)

A small, strong foundation for every table and every multi-step business
operation, audited against the seven tables that exist today
(`docs/audit/DATABASE_TRANSACTION_INTEGRITY_AUDIT.md`):

- **Foreign keys are actually enforced in dev/test, not just declared.**
  SQLite silently ignores `ForeignKey()` unless `PRAGMA foreign_keys=ON`
  is set per connection — verified missing, then fixed with a
  `connect`-event listener on this project's own engine
  (`app/core/database.py`), so local dev/tests now enforce exactly what
  MySQL (the one supported production database) already enforces.
- **Every foreign key has an explicit `ON DELETE` behaviour** — `RESTRICT`
  for organisation-scoping and the audit trail (never orphan a business
  record by deleting its parent), `CASCADE` for pure session/membership/
  grant rows, `SET NULL` for `audit_events.user_id`/`actor_user_id` (the
  audit row outlives the user it references). A `naming_convention` on
  `Base.metadata` gives every constraint a deterministic, addressable
  name going forward (migration `0010`).
- **One commit per logical operation.** `auth_service.login()` and
  `refresh()` used to commit the business change (last login / token
  revocation) and the new refresh token as two separate transactions —
  a failure between them could leave a false "login succeeded" audit
  record, or burn a refresh token with no replacement ever issued. Both
  now commit exactly once for the whole operation, with regression tests
  that force a failure between the former two commits and assert
  nothing partially persisted (`tests/test_database_integrity.py`).
- **Indexed for the query that actually runs.** The login-lockout check
  (`action` + `username_attempted` + `created_at` range) runs on every
  login attempt; it now has a matching composite index instead of a
  standalone one on a single column (migration `0012`).
- Two small pre-existing issues caught along the way: a schema/model
  width drift on `audit_events.action` (migration `0011`, found via
  `alembic check`) and a stale constraint name left over from the
  `auth_events` → `audit_events` rename.

No `Numeric`/`DECIMAL` columns or atomic stock/quantity updates exist
yet — there's no Sales/Finance/Products/Materials table to apply them
to. When one is built, it must use `Numeric`, never `Float`, for money
or quantities, and reuse `app/core/currency.round_currency` for rounding.

### Logging + Request Tracing (docs/modules/logging_request_tracing.md)

One structured, JSON-lines logger for the whole application, correlated
by request ID (`docs/audit/LOGGING_REQUEST_TRACING_AUDIT.md`):

- **`app/core/logging.py`** is the one place logging is configured —
  `get_logger(name)` for any module, `log(logger, level, message,
  **fields)` for a structured line. Every line always carries
  `timestamp`/`level`/`request_id`/`user_id`/`organisation_id`/`module`/
  `message`, plus whatever structured fields the call site adds
  (`action`, `duration_ms`, `error_code`, ...). `redact()` masks any
  field whose key looks sensitive (password, token, secret, ...) before
  it's ever written, as a safety net on top of never passing one in the
  first place.
- **`RequestLoggingMiddleware`** logs one line per completed request —
  method, route, status, `duration_ms`, the error code an exception
  handler left on `request.state` (if any) — at `INFO` normally, `WARN`
  above `SLOW_REQUEST_THRESHOLD_MS` (default 1000ms), `ERROR` on a 5xx
  — including when the handler itself crashes (see below).
- **Two real propagation bugs found while wiring this in**, both fixed:
  FastAPI runs synchronous dependencies/route handlers in a worker
  thread, so a `ContextVar` mutation made inside one (like
  `get_current_user` setting user identity) never propagates back to
  sibling code such as an exception handler — only `request.state`
  reliably crosses that boundary, so `user_id`/`organisation_id` are
  read from there, not the ContextVar, everywhere a `request` is
  available. Separately, a converted-to-response exception can
  re-propagate raw through a stacked `BaseHTTPMiddleware`'s own
  `call_next()` (a known Starlette quirk) — left unhandled, this
  silently dropped the completion log line for exactly the crashed
  requests that matter most; fixed by logging before re-raising.
- `request_id` itself is unaffected by either bug — set once in the
  outermost middleware before any thread/task is spawned, so it
  correctly reaches every descendant, verified by a test asserting the
  same id appears in the error-handler log line, the request-completion
  log line, the `X-Request-ID` response header, and the JSON error
  body's own `request_id` field, all for one request.
- Business audit trail (`audit_events`) and technical logs stay two
  separate concerns, unchanged by this phase: audit is what happened to
  business data and who did it; logs are what the application did while
  processing it.

Deliberately not built: no background-job system exists in this repo,
so #9's job-ID/originating-request-id chaining has no caller yet — the
mechanism it should reuse (`get_request_id()`/`set_request_id()`)
already exists. Log storage/rotation/retention is the deploying
platform's job (stdout + a log driver/aggregator), not application
code — `LOG_LEVEL` is the one piece of that this app owns directly.

### File / Storage Foundation (docs/modules/file_storage.md)

One shared storage layer — modules never implement their own file
storage logic (`docs/audit/FILE_STORAGE_AUDIT.md`):

- **`app/core/storage.py`**: a `StorageBackend` protocol
  (`upload`/`download`/`delete`/`exists`/`metadata`) and
  `LocalStorageBackend`, the "start simple" step — a future S3/Azure
  Blob backend is one new class implementing the same protocol, no
  caller changes.
- **Secure filenames.** `generate_storage_key()` never touches the
  user's filename — a fresh `f_<uuid4>.<ext>` every upload;
  `original_filename` is sanitized and stored separately, for display
  only, never for a filesystem path.
- **Server-side upload validation.** An allow-list of extensions (never
  a deny-list of dangerous ones), each with an expected magic-byte
  signature checked against the upload's actual bytes before anything
  is written to storage — a `.pdf`-named file that's actually an
  executable is rejected, regardless of the client-supplied
  `Content-Type`. Size is enforced while streaming
  (`MAX_UPLOAD_SIZE_MB`), not after buffering the whole file, and a
  rejected upload's partial write is cleaned up immediately.
- **`GET /api/files/{file_id}`**: authenticate → load scoped to the
  caller's organisation (404, not 403, for another organisation's file —
  never confirms it exists) → `app/core/entity_access.py`'s
  authorization hook → stream. The response never includes the physical
  `storage_key`.
- **Access control hook, not a hardcoded rule.** No business entity
  (Invoice, Quotation, ...) exists yet to own "who can view this
  record," so `entity_access.register_entity_access_check()` is the
  mechanism a future module registers its actual rule into;
  organisation-scoping alone is the baseline until one does.
- **Soft delete only.** `DELETE /api/files/{file_id}` sets `deleted_at`;
  the physical file is untouched. Physical deletion is a retention-policy
  decision this phase doesn't implement, since no such policy exists yet.

Storage backup is an operational requirement, not application code: the
`FILE_STORAGE_ROOT` directory must be included in whatever backs up the
database, since the database only holds references to the files in it.

### Background Jobs (docs/modules/background_jobs.md)

One database-backed job mechanism for work that shouldn't block a
request (`docs/audit/BACKGROUND_JOBS_AUDIT.md`):

- **`app/services/job_service.py`**: `dispatch`/`claim_pending_jobs`/
  `complete_job`/`fail_job`/`recover_abandoned_jobs`/`get_job_stats`.
  `dispatch()` doesn't commit -- include it in the same transaction as
  the business change it follows from for the atomic outbox case, or
  commit it alone right after for a plain "just enqueue this."
- **Job types are a closed set.** `app/core/job_registry.py` refuses an
  unregistered `job_type` at dispatch time; there is no endpoint that
  lets a client choose one. `app/jobs/__init__.py` registers every
  known handler at import time, the same pattern
  `app/models/__init__.py` uses for models.
- **Atomic claiming.** `claim_pending_jobs()` uses a conditional
  `UPDATE ... WHERE status='pending'` per candidate row, not a
  read-then-write -- portable to MySQL (this project's one supported
  production database), which has no `UPDATE ... LIMIT ... RETURNING`.
- **Retry only what a handler says is safe to retry.** A handler raises
  `RetryableJobError` for a transient failure; any other exception is
  non-retryable by default and fails immediately -- exponential backoff
  and a final `FAILED` state otherwise.
- **Crash recovery.** A `RUNNING` job whose worker never reported back
  within `JOB_STALE_RUNNING_MINUTES` is routed through the same
  retry/backoff logic as an ordinary failure, so a job type that
  reliably crashes its worker still reaches `FAILED` eventually.
- **A real transaction-safety bug found and fixed** while wiring a
  handler's writes into the same session as its job-status update: a
  handler that wrote something and then raised needed an explicit
  rollback before the failure was recorded, or that partial write would
  have been silently committed alongside the `FAILED` status. Covered
  by a dedicated test.
- **The one real job type**, not a fabricated demo:
  `cleanup_expired_refresh_tokens` -- expired refresh tokens have no
  value once past `expires_at`, and deleting rows that are already gone
  is naturally idempotent, so it doubles as this module's own
  idempotency proof.
- **`scripts/run_worker.py`** runs the one worker process (`python -m
  scripts.run_worker`); `scripts/enqueue_cleanup.py` is what a
  deployment's own cron calls once a day, per #10's "use the existing
  scheduler, don't build one."
- **`GET /api/jobs/stats`** (admin-gated): pending/running/failed/
  completed counts, oldest-pending age, last-success time.

Deliberately not built: a generic dispatch endpoint that accepts a
`job_type` from a client -- that's exactly the "let users arbitrarily
execute job types" #12 forbids. The worker running with minimum OS/DB
privileges is a deployment concern, not application code.

### Communication -- Email (`app/api/communication.py`)

One admin-configured mailbox per organisation, used both to verify a
real IMAP/POP3 connection and to send mail via SMTP. Ported from
`jdk_clean`'s single shared account (see `BT-Rajan/jdk_clean`'s
`app/services/email_account_service.py`/`email_service.py`) onto this
project's own foundations rather than copied as-is:
organisation-scoped like every other business table here
(`app/models/mixins.py`'s `OrganisationScopedMixin`, not a single
global row), `app/core/errors.py`'s `AppError` subclasses instead of a
separate exception hierarchy, and `app/core/validation.py`'s
`validate_email_format` reused rather than re-validated ad hoc.

- **`app/core/crypto.py`**: Fernet encrypt/decrypt for secrets that,
  unlike a login password, must be recoverable in plaintext to actually
  open a connection later. The key derives from `JWT_SECRET_KEY`
  instead of a second secret in `.env`.
- **`app/models/email_account.py`**: provider, address, encrypted
  password, IMAP/POP3/SMTP host+port+encryption settings, and the last
  test's result -- one row per organisation (`uq_email_accounts_organisation_id`),
  lazily created with Gmail's preset defaults on first read.
- **`GET /api/communication/email/providers`**: preset host/port values
  per provider (Gmail, Outlook, Yahoo, iCloud, custom) for the
  frontend's picker to fill the form with.
- **`GET`/`PUT /api/communication/email`** (admin-gated): read/save the
  organisation's mailbox. Saving validates the password policy is *not*
  re-applied here (a mailbox password isn't a login password) but does
  reject an IMAP/POP3 port that contradicts its own encryption setting
  (993/995 are SSL/TLS-only, 143/110 never are) and logs a
  `email_account_updated` audit event. `password: null` keeps the
  existing one; `password: ""` clears it -- distinct outcomes a single
  optional field couldn't otherwise express.
- **`POST /api/communication/email/test`**: opens and immediately
  closes a real IMAP/POP3 + SMTP connection with the saved settings.
  Never raises -- a failure comes back as `{"ok": false, "message"}` so
  the UI can show it inline.
- **`app/services/email_service.py`** / **`POST /api/communication/email/send-test`**:
  the one place any future module (quotations, orders, ...) sends an
  email from, rather than each rolling its own SMTP code -- `send-test`
  exercises the exact same `send_email()` a real business document
  would use, proving the whole pipeline works, not just that
  credentials open a socket.

### Notifications (`app/api/notifications.py`)

One notification service every module calls (`docs/modules/notifications.md`)
instead of rolling its own -- `notification_service.notify(db, user_or_users,
...)` creates the record(s); this module owns read-status too. Never
becomes the data-discovery backdoor it easily could: every read/write
endpoint is scoped to `recipient_user_id == current_user.id`, always
-- no admin/role gate needed, because a user's own notifications are
exactly that.

- **`app/models/notification.py`**: type (`INFO`/`ACTION_REQUIRED`/
  `SUCCESS`/`WARNING`/`ERROR`), title, message, an optional entity
  reference + `target_url` (a pointer, never a copy of the business
  record), read/unread + timestamps. Not organisation-scoped via the
  usual `OrganisationScopedMixin` -- every real query filters by
  recipient, not organisation; `organisation_id` is stored only for the
  email job's benefit.
- **`GET /api/notifications`**, **`GET /api/notifications/unread-count`**,
  **`PATCH /api/notifications/{id}/read`**, **`POST /api/notifications/mark-all-read`**.
- **Email is optional and goes through the existing job system, never
  inline**: `notify(..., send_email=True)` dispatches
  `app/jobs/send_notification_email.py` (registered the same way
  `cleanup_expired_refresh_tokens` is), which reuses
  `email_service.send_email` -- the same body a document email would
  use, no separate richer template. A missing mailbox is a no-op, not a
  failure; a real SMTP failure retries via `RetryableJobError`, same as
  any other job.
- **Retention**: `app/jobs/cleanup_old_read_notifications.py` +
  `NOTIFICATION_RETENTION_DAYS` (default 90) purges read notifications
  past the window; unread ones are never auto-deleted. Important
  business history stays in the audit trail, which has no such sweep.
- **Two real call sites**, not left as unexercised infrastructure:
  `PATCH /api/users/{id}/role` and `POST /api/teams/{id}/members` each
  notify the affected user (an "important status change" and an
  "assignment" per the module's own examples) -- neither sends email by
  default.
- **Frontend**: `frontend/src/components/ui/NotificationBell.tsx` in
  `TopNav`'s actions slot -- the one standard in-app UI (bell, unread
  count, list, mark read/mark all read, click-through to `target_url`)
  every module's `notify()` call surfaces through, rather than each
  building its own widget. Polls the unread-count endpoint instead of
  holding a push connection open.

### Organisation (`app/api/organisations.py`)

The top-level data and access boundary (`docs/modules/organisation.md`),
audited before this pass touched anything -- the model, the
`OrganisationScopedMixin`/FK/index pattern every organisation-owned
table already follows, the DB-authoritative organisation context on
every request (`get_current_user` joins and filters
`Organisation.is_active`, never trusting the JWT's own unused `org`
claim), and deactivation blocking login/refresh/every request were all
already correct and are unchanged.

- **The one genuine gap**: no admin API to edit or activate/deactivate
  an organisation, because RBAC didn't exist yet when the module was
  first built. RBAC exists now, so `PATCH /api/organisations/me`
  (name/code/contact/address/currency/timezone, partial-update
  semantics) and `PATCH /api/organisations/me/status` (activate/
  deactivate) were added, gated with the existing `require_admin`
  dependency -- not a new super_admin-only tier, since `app/core/roles.py`
  already documents super_admin and admin as identical within their own
  organisation today. Both audit-log (`ORGANISATION_UPDATED`/
  `ORGANISATION_STATUS_CHANGED`) and are scoped to `admin.organisation_id`
  only -- there is no `organisation_id` field in either request schema
  to escape that scope with.
- **Deliberately still not built**: organisation creation via API.
  Creation stays bootstrap-only (`scripts/seed_admin.py`), per the
  module's own "don't build a tenant provisioning system or public
  registration" guidance -- unchanged by this pass. A consequence worth
  stating plainly: reactivating a deactivated organisation is
  unreachable through the new status endpoint too, since none of its
  users (the admin who deactivated it included) can authenticate once
  it's inactive -- reactivation is an operator action (direct database
  access) today, the same as creation already is.
- 10 new tests in `tests/test_organisation.py`: edit success/audit,
  non-admin 403, invalid timezone/currency (422), a code collision with
  another organisation (409, and the row is unchanged), an `id`/
  `organisation_id` field in the request body being silently ignored,
  organisation name uniqueness (mirroring the existing code-uniqueness
  test), an explicit cross-organisation isolation check on `/me` itself,
  and deactivate-locks-out-the-acting-admin via the new endpoint.

### Common list contract (`app/core/list_query.py`, `app/schemas/pagination.py`)

A follow-up to the Tables/Forms/Modals/Filters audit
(`docs/audit/TABLES_FORMS_MODALS_FILTERS_AUDIT.md`), prompted by actually
wiring `UsersPage` up as a real consumer instead of a second hand-rolled
fetch. `GET /api/users`/`GET /api/teams` previously used `skip`/`limit`
and returned a bare array -- no endpoint returned a total or supported
sorting, so the frontend's own `useServerTable` hook had never been
exercised against anything real.

- **`app/schemas/pagination.py`**: `PaginatedResponse[T]` (Pydantic
  generic) -- `data: list[T]` + `pagination: {page, page_size, total,
  total_pages}`. One envelope every list endpoint returns, not a
  per-module shape.
- **`app/core/list_query.py`**: `paginate(query, page, page_size)` counts
  and slices (`.order_by(None).count()` so a prior sort never skews the
  count); `apply_sort(query, sort_by, sort_direction, allowed, default)`
  maps a client-supplied `sort_by` string to a real column only through a
  fixed, per-endpoint allowlist dict -- an unrecognized field is a 422
  naming the allowed set, never a silent fallback and never a raw
  `order_by(getattr(Model, sort_by))` that would let a client order by
  (or probe the existence of) an arbitrary column such as
  `password_hash`.
- Applied to both `GET /api/users` and `GET /api/teams`
  (`_SORT_FIELDS` in each router), proving the contract on two
  independent resources rather than just one.

Deliberately not built: a generic query/filter-expression builder, saved
filters, or an advanced search language -- `apply_sort` takes an
already-validated allowlist key, the same size and shape as
`app/core/search.py`'s `apply_keyword_filter`, not a query engine.
16 new tests (`tests/test_list_query.py`) cover the primitive standalone
plus both real endpoints; `tests/test_users.py`/`test_teams.py`/
`test_search.py` were updated for the new response envelope, not
rewritten.

### Master Data: Categories (`app/api/categories.py`)

First entity of Phase 2 -- Master Data (`docs/modules/categories.md`),
audited against `jdk_clean` first (`docs/audit/CATEGORIES_AUDIT.md`):
`jdk_clean` has no category mechanism at all, just an unvalidated
free-text `category` string independently duplicated on three unrelated
tables with no dedup -- nothing to reuse from there. Built fresh,
structurally mirroring `Team` (`OrganisationScopedMixin`/`TimestampMixin`,
name/code/description/is_active, per-organisation unique constraints on
name and code, no hierarchy) but with a full admin-gated CRUD API from
the start, since RBAC already exists (Team's own create/edit API was
deferred to a later phase for exactly that reason when Team was first
built).

- `GET /api/categories`/`GET /api/categories/{id}` -- open to any
  authenticated organisation member (read-only reference data, not a
  privileged view), same list contract as Teams/Users
  (`list_query.py`/`search.py`/`PaginatedResponse`).
- `POST /api/categories`, `PATCH /api/categories/{id}` (partial update),
  `PATCH /api/categories/{id}/status` (activate/deactivate) --
  `require_admin`-gated, no new authorization layer. Name/code conflicts
  raise `ConflictError` (409) via the same flush-then-catch-`IntegrityError`
  pattern `PATCH /api/organisations/me` established, not a pre-check
  query. Audit-logged (`category_created`/`category_updated`/
  `category_status_changed`) under a new shared `MASTER_DATA_MODULE`
  constant -- every future Phase 2 master-data entity (Units of Measure
  next) logs under this same module name rather than growing a new
  constant per entity.
- No delete endpoint -- categories are deactivated, never hard-deleted,
  matching Users/Teams/Organisation.
- 24 new tests (`tests/test_categories.py`): list/get org-scoping and
  cross-org 404s, per-organisation name/code uniqueness at the DB level,
  admin-gated create/edit/status-change (403 for non-admin), duplicate
  name/code on create and edit (409), an `id`/`organisation_id` field in
  a PATCH payload being silently ignored, and audit events for every
  mutation. Verified live: create, a duplicate-name conflict rendering
  inline, edit, deactivate/reactivate, and the non-admin read-only view
  (list visible, no create/edit/status controls) against a real backend.

### Master Data: Units of Measure (`app/api/units.py`)

Second entity of Phase 2 (`docs/modules/units_of_measure.md`), audited
first (`docs/audit/UNITS_OF_MEASURE_AUDIT.md`) -- jdk_clean's own history
here is decisive, not just absent like Categories: it built a real
`units_of_measure` table with a `factor_to_base` conversion column,
removed it within a week for conflating a true physical ratio (ton->kg)
with a business-specific packaging assumption (bag->kg, its own seed
comment admitting "a configurable assumption") in one field, then landed
on a hardcoded DB `ENUM` with no conversion at all -- duplicated three
times (Python tuple, DB enum, frontend TS const) with no single source
of truth.

- Structurally identical to Categories (`OrganisationScopedMixin`,
  same admin-gated CRUD shape, same `MASTER_DATA_MODULE` audit
  constant/`GET` open-read pattern) with two deliberate differences:
  `code` is **required** (Category's is optional) and normalized to
  **upper-case** on every create/update -- both directly informed by the
  audit's `"kg"`/`"Kg"`/`"KGS"` drift finding, via `app/schemas/unit.py`'s
  `_normalize_code`.
- **No conversion mechanism of any kind** -- no `factor_to_base`, no unit
  category, no ratio field. An explicit, evidence-based decision
  documented in the audit and the module doc, not an oversight.
  Organisation-scoped like every other master-data table here, also an
  explicit decision (jdk_clean's global list reflects having no
  organisation concept at all, not a considered "units should be global"
  design).
- 27 new tests (`tests/test_units.py`): list/get org-scoping and cross-org
  404s, per-organisation name/code uniqueness at the DB level,
  admin-gated create/edit/status-change (403 for non-admin), duplicate
  name/code on create and edit (409, including a case-insensitive code
  collision proving normalization runs before the uniqueness check),
  blank/missing name or code rejected (422), code normalization on edit,
  and audit events for every mutation.

### Master Data: Customers (`app/api/customers.py`, `app/services/customer_scope.py`)

Third entity of Phase 2 (`docs/modules/customers.md`), and the first
high-volume operational master with a real ownership/visibility model,
audited first (`docs/audit/CUSTOMERS_AUDIT.md`) -- unlike Categories/
Units, jdk_clean has substantial, well-factored prior art here worth
reusing (a single nullable `assigned_to` FK, `created_by` deliberately
excluded from visibility, a consistently-applied scoping layer across
every Sales-adjacent module) alongside a ~50-column field set the large
majority of which jdk_clean's own comments admit has "no consumer
anywhere in this app" -- none of that bloat is reused; the Customer
model here carries only code/name/contact_person/phone/email/address/
assigned_to_user_id/is_active.

- **The permission-scope engine already existed and had never been
  used**: `docs/modules/permissions.md` had already built
  `role_permissions`/`user_permissions` (with a working `own`/`team`/`all`
  `scope` column), `authorization_service.get_effective_scope()`/`can()`/
  `get_user_team_ids()`, and a full admin-gated management API --
  genuinely working, tested code with zero callers, by that module's own
  explicit design ("no module exists yet to consult it"). Customers is
  the first real consumer: `app/services/customer_scope.py`'s
  `resolve_view_scope()`/`visible_customer_filter()`/`can_view_customer()`
  call that engine directly, adding only the Customer-specific mapping
  (OWN = `assigned_to_user_id == self`; TEAM = assigned to anyone sharing
  a team with the caller, via the existing `get_user_team_ids()` +
  a `user_teams` join) it was designed for but never had built.
- **View-scope defaults, not hardcoded rules**: `permissions.md` §4's
  own role-default table (Manager -> TEAM, Team Member -> OWN) is
  applied only as a fallback when no explicit `role_permissions`/
  `user_permissions` row exists for `module_key="customers"` -- an admin
  can override any role's or individual user's scope at any time via the
  existing permissions API, and that explicit grant always wins.
  `admin`/`super_admin` bypass unconditionally, the same as every other
  admin-gated action in this codebase.
- **Mutation authorization mirrors jdk_clean's own real, deliberately
  strict choice**: `GET`/`POST` (view/create) are open to any
  authenticated organisation member -- onboarding a customer is ordinary
  sales work -- but `PATCH .../{id}` (edit) and `PATCH .../{id}/status`
  are `require_admin`-gated, same as every other master-data mutation;
  even a manager cannot edit or deactivate an existing customer record,
  exactly matching jdk_clean's own `strict_write_guard=require_role("admin")`.
  Reassignment (`PATCH .../{id}/assign`) is the one narrow exception:
  admin-or-manager via a plain role check (`_require_can_assign`), not a
  new scope-table action -- directly adopted from jdk_clean's real
  `is_admin OR is_department_head` gate.
- A `team_member`'s new customer is always auto-assigned to themselves,
  silently overriding any client-supplied `assigned_to_user_id` -- they
  can create their own customers but can never assign one to someone
  else. A customer outside the caller's view scope 404s (never 403s)
  from `GET /api/customers/{id}` -- adopted directly from jdk_clean's
  own deliberate "never confirm existence" choice here.
- `code` is auto-generated (`app/core/id_formats.py`'s new `CUSTOMER_ID`
  format, reusing the existing prefix+digits utility rather than a
  parallel one) and never client-supplied. `phone` is normalized to
  digits-only **at write time** and DB-unique per organisation -- fixing
  jdk_clean's real, flagged defect (`_check_duplicate_phone` re-scanned
  every existing customer row in Python on every write). `name` is
  deliberately not deduplicated (external real-world data, matching
  jdk_clean's own actual behaviour, unlike Category/Team's internally
  curated labels).
- 34 new tests (`tests/test_customers.py`): organisation isolation,
  default OWN/TEAM/ALL scope resolution (including a manager correctly
  excluding a salesperson not on their team), explicit permission-table
  overrides of the default (proving real engine reuse), create
  auto-assignment and cross-organisation assignee rejection, phone/code
  uniqueness, admin-only edit/status-change (403 for manager and
  team_member), admin-or-manager assign (403 for team_member), 404-not-403
  for an out-of-scope record, and audit events for every mutation.
  Verified live with four real users (admin, manager, and two
  salespeople -- one on the manager's team, one not): each saw exactly
  the customers their resolved scope predicts, confirmed against actual
  HTTP responses, not just unit-level assertions.

### Master Data: Suppliers (`app/api/suppliers.py`)

Fourth entity of Phase 2 (`docs/modules/suppliers.md`), and deliberately
the lightest master built so far -- expected volume is ~10 suppliers per
organisation, per the user's own framing. Audited first
(`docs/audit/SUPPLIERS_AUDIT.md`): unlike Categories/Units, jdk_clean has
a real Supplier implementation, but most of it is CRM/workflow bloat
copy-pasted from its own Customer model (a full onboarding-status state
machine, 1-5 star rating, ID-document verification, per-supplier
approval-threshold overrides) with no real consumer -- none of that is
reused. The Supplier model here carries only
code/name/contact_person/phone/email/address/is_active.

- **No organisation-scoping precedent to follow or diverge from**:
  jdk_clean has zero `organisation_id`/tenant concept anywhere in its
  codebase (it's single-tenant) -- Supplier simply follows jdk_erp's own
  established `OrganisationScopedMixin` convention, the same as every
  other master.
- **No Supplier<->Material relationship yet, and that's deliberate**:
  jdk_clean's real `supplier_materials` join table (price, MOQ, lead
  time, `is_preferred`, `status`) is solid prior art worth reusing --
  but Products/Raw Materials don't exist in this codebase yet, so
  building the other half of that relationship now would be pure
  speculation (Principle 5). When those modules land, `supplier_materials`'
  shape is the template to reuse; until then, a future Procurement module
  references a supplier directly on a purchase order with no catalog
  constraint.
- **Fully admin-gated, unlike Customer**: create/edit/activate-deactivate
  all require `require_admin` -- there is no ownership/assignment
  dimension to a ~10-record vendor list, so this reuses Category/Unit's
  plain admin-gated shape rather than a scaled-down version of Customer's
  permission-scope engine. Read stays open to any authenticated
  organisation member, same reasoning as every other master.
- `code` is auto-generated (`app/core/id_formats.py`'s new `SUPPLIER_ID`
  format, prefix `SUP`) via the same generate-with-retry-on-conflict
  approach `POST /api/customers` uses. `phone` is normalized to
  digits-only at write time and DB-unique per organisation, the same fix
  already applied to Customer's O(n) duplicate-phone defect -- jdk_clean's
  real Supplier implementation repeats that exact defect independently
  (`_check_duplicate_phone`, a fresh Python re-scan on every write).
  Unlike Customer, `name` **is** unique per organisation here -- a
  supplier is a small, internally curated vendor list (closer to
  Category/Unit in spirit) rather than externally-given high-volume
  business data.
- 26 new tests (`tests/test_suppliers.py`): organisation isolation,
  sequential code generation, phone normalization, name/phone
  uniqueness per organisation, admin-only create/edit/status-change
  (403 for non-admin), 404 for a cross-organisation id, and audit events
  for every mutation. Verified live: an admin creating a supplier saw
  the auto-generated `SUP0001` code and normalized phone rendered
  correctly, a duplicate-name attempt surfaced the 409 inline, a
  team_member saw the same list with no mutating controls, and
  deactivating updated the status badge immediately.

### Master Data: Products (`app/api/products.py`)

Fifth entity of Phase 2 (`docs/modules/products.md`) -- the authoritative
definition of what JDK sells and manufactures (~20 products per
organisation). Audited first (`docs/audit/PRODUCTS_AUDIT.md`): jdk_clean
has a real, fairly disciplined ~20-field Product with no variant/
attribute-builder bloat, but two critical gaps the user explicitly called
out: **no Customer Lead Time field or delivery-calculation engine exists
anywhere in jdk_clean** (Sales there negotiates delivery dates by hand),
and Manufacturing Lead Time isn't a literal field either -- it's a rate
(hours/unit) feeding a live capacity-scheduling engine consumed only by
Feasibility, never by Order's delivery-date logic. Both fields are
therefore designed fresh here, as simple, deliberately distinct reference
values (`manufacturing_lead_time_days`, `customer_lead_time_days`) --
never a calculation engine of any kind -- matching the user's own
architecture diagram exactly (Product holds the reference number; a
future Feasibility/Quotation/Order module turns it into an actual
commitment, snapshotting whatever value it used onto its own transaction
row so a later Product change can never rewrite history).

- **`code` is system-generated and immutable, same mechanism as
  Customer/Supplier**: `app/core/id_formats.PRODUCT_CODE` (prefix `2` +
  a 5-digit per-organisation sequence) -- per explicit user instruction
  that every Phase 2 master's code be auto-assigned, superseding the
  original decision to preserve jdk_clean's manually-assigned code.
  `ProductUpdateRequest` has no `code` field either way.
- **First real FK relationship between two master-data tables**:
  `category_id`/`unit_of_measure_id` are required FKs to the existing
  Category/UnitOfMeasure masters, validated on every create/update to be
  an *active* record in the caller's own organisation --
  jdk_clean itself briefly built a real units-of-measure master then
  reverted to a free-text enum a week later; that reversal is not
  followed here since jdk_erp's own masters already exist and are
  correct to reference.
- **Deliberately deferred, not invented ahead of a real consumer**:
  `product_type` (jdk_clean has a real finished_good/sub_assembly
  distinction, but its only consumer is BOM's component polymorphism,
  and BOM doesn't exist yet), a reorder-point/max-stock threshold pair
  (jdk_clean has one, but Inventory doesn't exist yet either), barcode,
  weight, and reference cost (none exist anywhere in jdk_clean at all).
  No delete guard either -- nothing in jdk_erp references `products` yet;
  jdk_clean itself has no delete guard on Product despite having real
  consumers, a gap explicitly not repeated once a first consumer exists.
- Same admin-gated shape as Category/Unit/Supplier (no ownership
  dimension, so no permission-scope engine) -- not jdk_clean's own
  department-permission-matrix gate for this module.
- 35 new tests (`tests/test_products.py`): organisation isolation, code/
  name uniqueness, immutable code (a `code` sent on PATCH is silently
  ignored), active-and-same-organisation validation for both category and
  unit of measure (422 for missing/inactive/cross-organisation), negative
  price/lead-time rejection, admin-only create/edit/status-change (403
  for non-admin), 404 for a cross-organisation id, audit events for every
  mutation, and a pin-down test documenting that `GET /api/products/{id}`
  always reflects Product's live price -- the obligation for whichever
  Quotation/Order module is built next to snapshot price itself.

### Master Data: Raw Materials (`app/api/raw_materials.py`, `app/api/raw_material_suppliers.py`)

Sixth entity of Phase 2 (`docs/modules/raw_materials.md`) -- the
authoritative material identity bridging Supplier -> Purchase Order ->
Receipt -> Inventory on one side, and BOM -> Production on the other.
Unlike every prior master, the user asked for this one to be "as
detailed as Product, but with the detail concentrated on relationships
rather than generic ERP fields" -- Raw Material itself stays as lean as
Category/Unit/Supplier (~5 materials expected); the depth goes entirely
into a new `SupplierMaterial` join table.

Audited first (`docs/audit/RAW_MATERIALS_AUDIT.md`): jdk_clean has a
real, disciplined ~15-field Raw Material and a well-designed (if
under-consumed) `supplier_materials` relationship table, but Purchase
UoM/conversion, BOM, Purchase Order, Receipt, and Inventory are either
absent from jdk_clean entirely or have zero prerequisite infrastructure
in jdk_erp today.

- **`RawMaterial` mirrors `Product`'s shape exactly**: system-generated
  immutable `code` (`app/core/id_formats.RAW_MATERIAL_CODE`: prefix `1`
  + a 5-digit per-organisation sequence), required active-
  and-same-organisation Category/UnitOfMeasure FKs, one reference-cost
  field (kept, unlike Product's -- jdk_clean's `unit_cost` is genuinely
  consumed as a PO-pricing default and inventory-valuation input, unlike
  Product's absent equivalent). Same admin-gated CRUD shape as Category/
  Unit/Supplier/Product, not jdk_clean's own department-permission-matrix
  gate for this module.
- **`SupplierMaterial` is the one relationship built with real depth**:
  a new join table (`supplier_id`, `raw_material_id`, CASCADE both ways,
  no `organisation_id` of its own -- shaped like this codebase's own
  `UserTeam`, a join between two already org-scoped entities) carrying
  `supplier_material_code` (the supplier's own SKU, distinct from the
  material's own code), `purchase_price` (a reference/default value,
  never live-read into a transaction -- there being no PO module yet to
  read it), `lead_time_days`, `moq`, `max_supply_quantity`, and
  `is_preferred` (at most one per material, enforced service-side only
  via silent unset, matching jdk_clean's own real, deliberate
  `_enforce_single_preferred` behaviour exactly -- no DB constraint, no
  rejected write). A material may have zero, one, or many suppliers, no
  minimum enforced, matching jdk_clean's confirmed real behaviour.
- **Deliberately not reproduced from jdk_clean's `supplier_materials`**:
  `currency` (this codebase's `Organisation.currency` already covers
  it), `onboarded_at`/`last_transaction_at` (both are only ever written
  by an actual PO receipt event in jdk_clean -- dead columns without that
  module), and the separate pause-vs-sever (`status` vs `deleted_at`)
  distinction (a plain `is_active` covers pausing; severing is a real,
  hard `DELETE` -- nothing yet needs to distinguish "paused" from
  "severed but historically referenced," since no transaction table
  exists yet to reference a severed relationship).
- Nested API surface: `GET/POST /api/raw-materials/{id}/suppliers`,
  `PATCH/DELETE /api/raw-materials/{id}/suppliers/{link_id}` -- open read,
  admin-gated mutations, same gate as the Raw Material record itself.
  `supplier_id` is validated active-and-same-organisation on add, same
  treatment as Product's category/unit validation.
- **Purchase UoM/conversion factor is not built** -- jdk_clean has no
  such concept anywhere despite live procurement (a confirmed gap, not
  prior art), and the spec explicitly warns against building a
  conversion engine speculatively. If ever needed, it belongs on
  `SupplierMaterial` (per-relationship), not on `RawMaterial`.
- **BOM, Purchase Order, Receipt, and Inventory are all deferred in
  full** -- confirmed zero prerequisite infrastructure in jdk_erp today;
  each boundary rule (no stock quantity on RawMaterial, PO/receipt lines
  must snapshot price and never live-read RawMaterial/SupplierMaterial,
  deactivating a material must never silently touch a BOM) is documented
  in the module spec as binding for whenever those modules are built.
- 41 new tests (`tests/test_raw_materials.py`, `tests/test_raw_material_suppliers.py`):
  organisation isolation, code/name uniqueness, immutable code,
  active-and-same-organisation validation for category/unit/supplier,
  add/list/edit/remove a supplier relationship, duplicate
  (supplier, material) pair rejection (409), single-preferred-supplier
  enforcement on both add and update, zero-suppliers-is-a-valid-state,
  admin-only mutations (403 for non-admin) including on
  `SupplierMaterial`, 404 for a cross-organisation id, and audit events
  for every mutation on both `RawMaterial` and `SupplierMaterial`.

### Master Data: Machines & Production Lines (`app/api/machines.py`, `app/api/production_lines.py`)

Seventh entity of Phase 2 (`docs/modules/machines.md`) -- the
authoritative configuration of JDK's physical production resource. JDK
currently has exactly 1 machine, 1 production line, and a configured
capacity of ~2 tonnes/hour, so the master itself is deliberately tiny;
the one thing that had to be modeled properly is a real, structured,
configurable production rate.

Audited first (`docs/audit/MACHINES_AUDIT.md`): jdk_clean conflates
Machine and Production Line into a single, hard-singleton-enforced
`machines` table (its model docstring literally says the UI calls it
"Production Line" while the schema keeps the name "machine") whose only
capacity-shaped field is an *availability window*
(`capacity_hours_per_day`), not a rate. The real per-unit throughput
rate (`production_hours_per_unit`) lives entirely on jdk_clean's
Product, not on Machine, and there is no Machine<->Product rate join
table at all.

- **Machine and ProductionLine are built as genuinely separate
  entities**, unlike jdk_clean -- a deliberate departure per the user's
  own explicit instruction to distinguish them "even if there is
  currently only one." No singleton constraint is enforced either:
  ordinary admin-gated CRUD already produces "exactly one" today without
  a business rule that would need relaxing the moment a second line or
  machine is added.
- **Capacity is stored structurally as three columns on Machine**
  (`capacity_quantity` / `capacity_unit_of_measure_id` /
  `capacity_period_hours`), reusing jdk_erp's own existing UnitOfMeasure
  master rather than a free-text unit string or jdk_clean's
  availability-only scalar. Together these represent "quantity per
  period hours" -- e.g. 2 tonnes per 1 hour -- reconfigurable by an
  authorised user via a plain `PATCH` with no code change.
- **No Machine<->Product rate relationship is built.** The audit found
  jdk_clean's schema is *capable* of a per-product rate but found no
  evidence JDK's actual business has different real rates for different
  products -- only that the schema technically allows it. Per the user's
  own explicit instruction (build that relationship only if proven
  necessary; otherwise keep one configuration at the machine/line level)
  and because jdk_erp's own Product model deliberately carries no rate
  field at all, capacity is modeled once, at the Machine level. If real
  per-product rate variance is ever proven, that relationship is added
  then, against its own audit.
- Same admin-gated CRUD shape as every other master (no ownership
  dimension), not jdk_clean's own department-permission-matrix gate for
  this module. `production_line_id` and `capacity_unit_of_measure_id`
  are validated active-and-same-organisation on every write, the same
  treatment already given to Product/RawMaterial's Category/UoM FKs --
  as a direct query returning a uniform 422 for missing, inactive, *and*
  cross-organisation references alike, never a 404 that would leak
  whether a cross-org id exists.
- **No production-time calculation engine, no Feasibility integration
  code, and no historical capacity snapshotting are built** -- Feasibility
  and Production Scheduling don't exist in jdk_erp yet. jdk_clean's own
  formula (`required_hours = quantity * production_hours_per_unit`,
  fractional hours used directly, never rounded to whole hours) and its
  confirmed live-read-only design (no snapshotting anywhere) are both
  documented in the module spec as binding targets for whenever those
  modules are built, rather than implemented speculatively now.
- `code` is system-generated and immutable on both Machine and
  ProductionLine (no update path for it at all) --
  `app/core/id_formats.PRODUCTION_LINE_CODE`/`MACHINE_CODE` share a
  distinct `0000`-prefixed shape from the digit-per-entity masters
  (`"00001"`/`"00002"` + one free digit), capping each at 9 records --
  a real, intentional limit for these small, effectively-fixed-size
  masters, surfaced as a 400 if ever hit.
- 37 new tests (`tests/test_production_lines.py`, `tests/test_machines.py`):
  organisation isolation, code/name uniqueness, immutable code,
  active-and-same-organisation validation for production line and
  capacity unit (422 for missing/inactive/cross-organisation), strictly-
  positive capacity validation, reconfiguring capacity without a code
  change, admin-only create/edit/status-change (403 for non-admin), 404
  for a cross-organisation id, and audit events for every mutation on
  both `Machine` and `ProductionLine`.

### Master Data: Warehouses (`app/api/warehouses.py`)

Eighth entity of Phase 2 (`docs/modules/warehouses.md`) -- the
authoritative physical storage location inside the JDK factory and its
configured total storage capacity. JDK has exactly 1 warehouse; this is
explicitly not a Warehouse Management System.

Audited first (`docs/audit/WAREHOUSES_AUDIT.md`): jdk_clean has **no
warehouse/location entity at all** -- "warehouse" there is only one row
in its generic `departments` table, used purely to gate which users see
warehouse-scoped dashboard notifications, never a data row with its own
identity or capacity. Confirmed via exhaustive grep: no storage-area/
capacity/footprint/volume concept exists anywhere in jdk_clean either,
except one confirmed-dead free-text field
(`raw_materials.storage_location`, explicitly commented as "not read by
any business logic").

- **A genuinely new master, not a jdk_clean refactor** -- there was
  nothing to reuse or diverge from for the entity itself.
- **Structured, configurable total capacity**: `total_usable_storage_area`
  + `storage_area_unit_of_measure_id`, reusing jdk_erp's own existing
  UnitOfMeasure master (validated active and same-organisation, the same
  treatment Machine gives its own capacity unit) -- reconfigurable via a
  plain `PATCH`, no code change, mirroring Machine's own capacity-
  reconfiguration pattern exactly.
- **No per-material/per-product storage-requirement field, and no
  required/available-area calculation are built.** The audit found zero
  evidence anywhere in jdk_clean of a real storage-area-per-unit
  business rule, and even if one existed, the calculation is
  uncomputable today regardless -- there is no Inventory/Stock Ledger in
  this codebase yet to supply live stock quantities. Both are documented
  in the module spec as deferred decisions for whenever Inventory is
  built and the need can be evaluated against real usage.
- **No warehouse-in/out, stock ledger, hierarchical locations
  (zone/aisle/rack/bin), or geographic/logistics fields are built** --
  none exist in jdk_clean either, and Procurement/Production/Sales/
  Delivery all have zero prerequisite infrastructure in jdk_erp. Every
  boundary (Warehouse never owns stock quantities/movements; a future
  Inventory module is the sole authority) is documented as binding for
  whenever those modules land.
- Same admin-gated CRUD shape as every other master -- there's no
  jdk_clean gate to diverge from here either, since "warehouse" in
  jdk_clean is a permission label, not an entity with its own access
  rule.
- `code` is system-generated and immutable --
  `app/core/id_formats.WAREHOUSE_CODE` (`"00003"` + one free digit,
  capping at 9 records, the same `0000`-prefixed shape as
  ProductionLine/Machine).
- 21 new tests (`tests/test_warehouses.py`): organisation isolation,
  code/name uniqueness, immutable code, active-and-same-organisation
  validation for the storage-area unit (422 for missing/inactive/
  cross-organisation), strictly-positive area validation, reconfiguring
  capacity without a code change, admin-only create/edit/status-change
  (403 for non-admin), 404 for a cross-organisation id, and audit events
  for every mutation.

### Master Data: Bill of Materials (`app/api/boms.py`, `app/services/bom_service.py`, `app/services/uom_conversion.py`)

Ninth entity of Phase 2 (`docs/modules/boms.md`) -- the single,
unambiguous relationship between a finished Product and the Raw
Materials required to produce a specified base quantity of it. A
hardening pass over a real jdk_clean feature, not a new module built
from nothing.

Audited first (`docs/audit/BOMS_AUDIT.md`): jdk_clean has a genuinely
working, multi-level BOM (`Bom`/`BomLine`, sub-assemblies via a
polymorphic component, cycle detection, `scrap_percent`) and a real
persisted Production Order material-requirement snapshot with explicit
protection against recalculation once execution starts. But its one
real attempt at unit conversion -- a `units_of_measure` table with a
single `factor_to_base` column doing double duty as both a universal
ratio (`1 ton = 1000 kg`) and a material-specific packaging assumption
(`1 bag = 50 kg`, per the seed data's own comment: *"edit this row's
factor_to_base ... if that's wrong for what's actually being
bagged"*) -- was built, then dropped nine days later. What replaced it
sidesteps cross-unit BOMs entirely (a BOM line's unit is always forced
equal to its component's own unit; fake units like `"20kg"`/`"25kg"`
stand in for real packaging conversion) rather than solving the
problem this module's spec requires solving.

- **Two deliberately separate conversion mechanisms**, never one
  conflated column: `UnitOfMeasure.dimension` +
  `conversion_factor_to_base` for universal, dimensional ratios
  (kg/g/tonne all share `dimension="mass"`) -- the "safe half" of
  jdk_clean's removed mechanism; `RawMaterial.alternate_conversion_
  unit_of_measure_id` + `alternate_conversion_factor` for
  material-specific ratios (density, packaging) -- the "unsafe half,"
  scoped to the one material it's actually true for. Both pairs are
  nullable and always both-set-or-both-null, enforced at the API layer
  even on partial `PATCH` updates. `app/services/uom_conversion.
  resolve_conversion_ratio` chains at most one material-specific hop
  plus one further universal hop -- never a generic multi-hop
  conversion graph.
- **Every component validated at save time**: `app/services/
  bom_service.require_valid_component_conversion` rejects (422) a
  component with no valid conversion between its own unit and the
  Product's unit, with a specific, actionable error naming exactly
  what needs configuring -- never a silent assumption or a silently
  rounded-away mismatch. The same check re-runs at activation.
- **Quantity is the one authoritative value**: `BomComponent.quantity`
  is always stored in the material's own unit, never converted at
  rest. Percentage is computed at read time only
  (`bom_service.component_percentage`), never stored, never
  independently editable.
- **Production requirement calculation** (`POST /api/boms/{id}/
  calculate-requirements`): `Required = Component Qty * Production
  Qty / Base Qty`, computed per component, staying in that component's
  own unit -- a pure, stateless calculation with no persistence of its
  own, since Production Order doesn't exist in this codebase yet
  (building even a minimal one now would merge responsibilities the
  spec's own boundary keeps separate). jdk_clean's real snapshot-
  protection behavior (never silently recalculate over a committed
  production order) is documented in `docs/modules/boms.md` #10 as
  binding for whichever future Production Order module is built --
  flagged explicitly, not silently skipped.
- **One BOM per product** (`UniqueConstraint(organisation_id,
  product_id)`), directly reusing jdk_clean's own real, sound design.
  Status is `draft`/`active` (renamed from jdk_clean's `active`/
  `inactive` for clarity). Activating requires >=1 component and every
  component's conversion still resolvable -- a hardened version of
  jdk_clean's own real `component_count(...) > 0` activation gate.
  Duplicate raw-material components are blocked by a DB
  `UniqueConstraint(bom_id, raw_material_id)`, hardening jdk_clean's
  app-level-only check.
- **Not carried over from jdk_clean, flagged rather than silently
  dropped**: multi-level/sub-assembly BOMs (no proven need, out of
  spec scope), `scrap_percent` (outside the spec's own formula), the
  `factor_to_base` conflated-conversion mechanism (the precise
  anti-pattern this module exists to avoid), and the persisted
  Production Order requirement snapshot (no Production Order exists
  yet to snapshot onto).
- Read (list/get/calculate-requirements) is open to any authenticated
  organisation member; create/edit/component management/activation are
  admin-gated -- jdk_clean gates BOM read behind `admin` entirely, not
  followed here, matching every other jdk_erp master's split instead.
- 69 new/changed tests: `tests/test_uom_conversion.py` (9, the
  conversion service directly -- same-unit, universal, no-conversion-
  across-dimensions, material-specific density/packaging, one
  material-specific hop chained with one universal hop, inverse
  direction, an override that doesn't apply to the pair being
  converted), `tests/test_boms.py` (44 -- the full #14 conversion
  matrix, organisation isolation, one-BOM-per-product uniqueness,
  component CRUD, duplicate-component rejection, activation gating,
  defensive re-check when a material's unit changes after a component
  was added, stateless/live requirement calculation, RBAC, audit
  events), plus new coverage in `tests/test_units.py` and
  `tests/test_raw_materials.py` for the new conversion field pairing/
  positivity/self-reference validation on create and edit.

## Setup

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

cp .env.example .env
# generate a real secret and put it in .env:
python -c "import secrets; print(secrets.token_hex(32))"

alembic upgrade head
python -m scripts.seed_admin   # creates the first organisation + user
uvicorn app.main:app --reload
```

## Tests

```bash
source .venv/bin/activate
pytest
```
