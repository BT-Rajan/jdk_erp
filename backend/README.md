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
  `GET /api/users` (paginated, active-only by default) and `GET
  /api/users/{id}`, both scoped to the caller's own organisation (a
  cross-organisation lookup returns 404, never confirming another
  organisation's user exists). Matches
  [`../docs/modules/users.md`](../docs/modules/users.md). Deliberately
  **excludes** create/edit/deactivate/assign-role endpoints — same reason
  as organisation's admin API: they need an "authorised administrator,"
  which only RBAC can define, and gating them with anything less (e.g. an
  `is_admin` flag on `User`) would put permission logic on the User
  record itself, which the spec explicitly forbids. `UserOut`
  (`app/schemas/user.py`) is now the one public-safe user shape, shared
  between `/api/auth/me` and the directory endpoints.
- **Teams** (`app/api/teams.py`, `app/models/team.py`) — organisational
  grouping only, no permission data: `GET /api/teams`, `GET
  /api/teams/{id}`, and `GET /api/users?team_id=...` to view a team's
  members (reusing the existing directory endpoint rather than adding a
  new one). Team name and code are unique *within* an organisation (not
  globally — teams aren't a login identifier, so there's no
  disambiguation problem the way there was for usernames). Matches
  [`../docs/modules/teams.md`](../docs/modules/teams.md). Deliberately
  **excludes** create/edit/deactivate/assign-user endpoints, same
  reasoning as Organisation and Users. Also deliberately excludes two
  things `jdk_clean`'s equivalent (`Department`) had: a
  department-to-page permission matrix (that's RBAC's job, not a team's)
  and a `manager_id` reporting-line column (a manager's scope should be
  `role = Manager` + `team`, not a separate hierarchy) — see
  [`../docs/audit/TEAMS_AUDIT.md`](../docs/audit/TEAMS_AUDIT.md).

Every gap the audit found has a fix in this implementation:

| Audit finding | Fix |
| --- | --- |
| Hardcoded default JWT secret | `JWT_SECRET_KEY` has no default — app refuses to start without it (`app/core/config.py`) |
| No login rate limiting | Rolling-window lockout by username (`app/services/auth_service.py`, `LOGIN_LOCKOUT_THRESHOLD`/`_WINDOW_MINUTES`) |
| No authentication audit trail | `auth_events` table logs every login success/failure, logout, password change (`app/models/auth_event.py`) |
| Timing/enumeration leaks | Password verification always runs (dummy hash for unknown users); one generic message for bad password / unknown user / inactive account |
| Password policy was length-only | Full complexity check — length, uppercase, digit, special character (`app/core/validation.py`) |
| Vestigial `role` claim in JWT | Not present — the access token carries only `sub`/`org` |
| `users` table missing `organisation_id`/`last_login` | Both present from the start (`app/models/user.py`) |

Deferred, not forgotten (see the audit doc's action items): mobile secure
token storage, unifying frontend/mobile refresh clients, and CLI-script
consolidation — none of these apply yet since no frontend/mobile app
exists in this repo yet.

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
