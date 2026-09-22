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
  another organisation's user exists). Matches
  [`../docs/modules/users.md`](../docs/modules/users.md). Still
  **excludes** create/edit/deactivate — those need a fuller "authorised
  administrator" story than the role gate RBAC adds below covers; only
  `PATCH /api/users/{id}/role` (admin-gated) is built, since that's what
  the RBAC phase explicitly asked for. `UserOut` (`app/schemas/user.py`)
  is the one public-safe user shape, shared between `/api/auth/me` and
  the directory endpoints, carrying `role` and `team_ids`.
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
