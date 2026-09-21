# Authentication Audit — `jdk_clean`

Phase 0 audit of the authentication layer only (login, logout, password
handling, session/token issuance and validation, current-user resolution),
per [`../ROADMAP.md`](../ROADMAP.md) and the spec in
[`../modules/authentication.md`](../modules/authentication.md).
Authorization/RBAC is out of scope here except where it touches
authentication — that gets its own audit before Phase 1 RBAC work starts.

Every finding below is evidence-based, with file:line citations against
`jdk_clean/backend`, `jdk_clean/frontend` and `jdk_clean/mobile-app-rn`.

## Verdict

**Reuse and harden, do not rewrite.** The existing implementation
(FastAPI + SQLAlchemy/MySQL + bcrypt + JWT access token with a rotated,
server-revocable refresh token) is a sound design, cleanly separated from
authorization in the one place that matters (`get_current_user` touches
no roles/permissions). It does not meet the full spec in
`authentication.md` yet — no auth audit trail, no rate limiting, an unsafe
default secret, a couple of minor enumeration leaks — but none of that
requires a different framework or a different token strategy. Port it
forward and close the gaps listed under "Action items."

## 1. Stack

- **Backend**: FastAPI (`backend/app/main.py`), SQLAlchemy 2.x ORM over
  MySQL, schema hand-authored in `backend/schema.sql` plus an append-only
  `backend/migrations/*.sql`, applied at startup (`app/core/migrations.py`).
- **Session/token mechanism**: no server session, no cookies. Stateless
  **JWT access token** (60 min TTL) + a **JWT refresh token** whose `jti`
  is persisted server-side in a `refresh_tokens` table so it can be
  revoked and rotated (`app/core/security.py`, `app/models/refresh_token.py`).
- Raw SQL (`sqlalchemy.text()`) appears alongside the ORM in places like
  `audit_service.py`, but every instance found uses bound parameters —
  not a security issue, just two data-access styles in one codebase.

## 2. User identity model

`users` table (`backend/schema.sql:68-101`, `app/models/user.py:18-82`):
`id`, `username` (unique), `email` (unique), `password_hash`, `full_name`,
`phone`, `avatar_filename`, `department_id` (FK), `manager_id`
(self-FK, org-chart display only), `signature_filename`, `role` (enum,
see below), `is_active`, soft-delete (`deleted_at`), and
`created_at`/`created_by`/`updated_at`/`updated_by`.

- **Single-tenant**: no `organisation_id`/tenant table exists anywhere in
  the schema. The spec calls for one — this is a real gap, not just a
  missing column, since it shapes every other table too.
- **No `last_login` column** — login events aren't recorded on the user
  row at all.
- **One `users` table**, no duplicate/shadow identity table.
  `email_accounts`/`sms_accounts`/`whatsapp_accounts` are unrelated
  communication-channel credential stores, not identity duplicates.

## 3. Login flow

`POST /api/auth/login` (`api/auth.py:38-41`) → `auth_service.login`
(`services/auth_service.py:34-40`). Username + password only (no email
login). Password check via bcrypt (`core/security.py:17-18`), inactive
users rejected, tokens issued via `_issue_tokens()`
(`auth_service.py:17-31`). The response (`TokenResponse`) carries no user
fields or password data; profile comes from a separate `GET /api/auth/me`
whose `MeOut` schema excludes `password_hash` entirely.

Gaps found:

- `user is None or not verify_password(...)` (`auth_service.py:36`) skips
  bcrypt entirely when the username doesn't exist — a timing side-channel
  that lets an attacker distinguish "no such user" from "wrong password."
- The deactivated-account error message differs from the generic
  invalid-credentials message (`auth_service.py:37` vs `39`) — leaks that
  an account exists but is disabled.
- **No rate limiting or lockout** on `/api/auth/login` — unlimited online
  brute force is possible today.
- **No login attempt logging**, success or failure (see §7).

## 4. Password handling

- Hashing: bcrypt via `passlib`, used consistently everywhere a password
  is set (`core/security.py:10`; `auth_service.py:99`; `api/users.py:61`;
  all three bootstrap scripts).
- Policy: **minimum 8 characters only** — enforced via Pydantic
  `Field(min_length=8)` in three schemas and mirrored in three CLI
  scripts. **No complexity requirements** (no uppercase/digit/symbol
  checks) — the spec calls for all three; this needs to be added.
- Self-service change-password (`api/auth.py:56-63`) requires the current
  password, rejects only exact reuse of the current password (no real
  history check), and correctly **revokes all outstanding refresh tokens**
  on success, forcing re-login everywhere.
- Admin reset (`api/users.py:123-140`, admin-only) doesn't require the old
  password, also revokes all refresh tokens, and — good practice — writes
  a **redacted** audit row (`"[redacted]"`/`"[reset by admin]"`) rather
  than ever touching the real value.
- No password is ever logged: `request_logging.py` deliberately does not
  log request bodies, and the generic audit logger only records diffs of
  non-sensitive fields.
- One inconsistency: `scripts/seed_admin.py` takes `--password` as a CLI
  argument (leaks into shell history / `ps`), while `create_user.py` and
  `reset_password.py` correctly use `getpass.getpass()`.

## 5. Session/token security

- No cookies — tokens travel as `Authorization: Bearer <token>`, so
  HttpOnly/Secure/SameSite don't apply here; the tradeoff instead lands on
  the client's storage choice (see §9).
- TTLs: access 60 min, refresh 7 days (`core/config.py:35-36`).
- **Refresh-token rotation is implemented correctly**: each refresh call
  revokes the used `jti` and issues a new pair (`auth_service.refresh`,
  lines 43-66); replay of a revoked refresh token is detected and
  rejected.
- **Logout genuinely revokes server-side state** — it flips
  `refresh_tokens.revoked = True` for that token (`auth_service.py:69-78`),
  not just a client-side token drop. It does **not** revoke the still-live
  access token or a user's *other* refresh tokens on other devices — a
  known JWT tradeoff, but worth deciding on deliberately (e.g. shorter
  access TTL) rather than inheriting silently.
- **High-severity finding**: `JWT_SECRET_KEY` defaults to the literal
  string `"change-me-in-env"` (`core/config.py:33`). If a deployment ever
  runs without `.env` correctly populated — a failure mode the codebase's
  own comments admit has already happened — every token is signed with a
  publicly known secret, allowing full auth bypass and token forgery. The
  same secret also derives the Fernet key used to encrypt stored
  third-party mailbox credentials (`core/crypto.py:21-23`), so this one
  misconfiguration compromises two things at once.

## 6. Authentication vs authorization boundary

This is the cleanest part of the implementation. `get_current_user()`
(`api/deps.py:70-87`) validates the bearer token, checks it's an access
token (not a refresh token used as one), and loads the user — nothing
else. It touches no roles or permissions. `require_role()` and
`require_page_access()` (`api/deps.py:90-96`, `core/permissions.py`) sit
in a separate module and take the resolved user as an input, composed via
FastAPI's dependency injection rather than fused into one function. This
matches §6 of the authentication spec almost exactly as written.

Two things to fix in the rebuild rather than carry forward as-is:

- The JWT access token embeds `{"role": user.role}` at issue time
  (`auth_service.py:18`), but **nothing ever reads that claim back** —
  every authz check re-queries the live `User.role` from the database
  instead. It's dead data, readable by anyone holding the token (JWT
  payloads are base64, not encrypted). Drop it.
- `role` and `department_id` live on the same table as pure identity
  fields. Not a bug, but the identity model and the permission model
  aren't schema-separated — decide this deliberately when the RBAC audit
  happens, rather than by default.

## 7. Audit logging

There is a generic `audit_log` table used extensively for business-record
CRUD, and it happens to catch two auth-adjacent events: admin password
resets (explicit, redacted) and `is_active` toggles (incidentally, via the
generic update-diff logger). Everything else the spec requires is
missing: **no record of login success, login failure, logout, or
self-service password change.** The only trace of a login request at all
is a flat, unstructured HTTP access log
(`core/request_logging.py`) with no username and no success/failure
semantics beyond the HTTP status code — not queryable, not a security
audit trail.

## 8. Duplication / dead code

- No competing login endpoints, no duplicate token-verification helpers —
  `decode_token()` is the single source used everywhere.
- The three bootstrap CLI scripts (`create_user.py`, `reset_password.py`,
  `seed_admin.py`) each **re-implement** validation instead of importing
  the Pydantic schemas the API uses, and have already drifted:
  `create_user.py`'s `VALID_ROLES` tuple is missing the two newest role
  values, so it can't create a `department_head` or `team_member` today.
- No dedicated auth test file exists (`backend/tests/` has ~50 test files
  for business services, none for login/refresh/logout/password flows).
- Frontend and mobile each **independently reimplement** the
  token-refresh/401-retry interceptor (`frontend/src/api/client.ts` vs.
  `mobile-app-rn/src/api/client.ts`) — same behaviour, two codebases, no
  shared package.
- Client-side route guards (`ProtectedRoute`, `AdminOnlyGuard`,
  `PagePermissionGuard`) are UX-only and correctly not relied on for
  security — all real enforcement is server-side. Worth stating
  explicitly since Principle 3 depends on it holding true going forward.

## 9. Frontend / mobile

- **Web**: access token kept in memory only (lost on reload, recovered by
  silent refresh); refresh token in `sessionStorage` (cleared on tab
  close) — a deliberate, documented tradeoff, reasonable given no
  httpOnly-cookie option exists server-side.
- **Mobile**: both access and refresh tokens are stored in plain
  `AsyncStorage` — unencrypted, disk-backed, survives app restarts
  indefinitely. No OS secure storage (Keychain/Keystore/
  `expo-secure-store`) is used. This is a genuine, fixable weakness
  relative to the web app's approach.
- **Mobile has no change-password and no reset/forgot-password flow at
  all** — a real feature gap versus web, not just a UI gap.
- Each platform has its own `AuthContext`/`AuthProvider` with divergent
  capabilities — expected for two separate apps, but two auth state
  machines to maintain.

## 10. Other findings

- CORS allows all methods and headers (`allow_methods=["*"]`,
  `allow_headers=["*"]`) with `allow_credentials=True`, though origins
  are at least allowlisted rather than wildcarded.
- No password-length cap / bcrypt's 72-byte truncation isn't surfaced to
  the user — low impact, but silent.
- No SQL injection risk found anywhere on the authentication surface —
  every query is parameterized (ORM filters or bound `text()` params).

## Action items for Phase 1 (port forward, don't rewrite)

Status as of the `backend/` implementation in this repo:

1. ✅ Fail loudly at startup if `JWT_SECRET_KEY` is unset — no default
   exists (`app/core/config.py`); confirmed by test (import fails with a
   `pydantic.ValidationError` when the env var is missing).
2. ✅ Login rate limiting / lockout — rolling-window lockout by username
   (`app/services/auth_service.py`, backed by `auth_events`).
3. ✅ Real authentication audit trail — `auth_events` table records login
   success, login failure (with a `reason`), logout, and password change.
4. ✅ Enumeration/timing leaks fixed — password verification always runs
   (against a dummy hash when the user doesn't exist); unknown user,
   wrong password and inactive account all return the identical generic
   message.
5. ✅ Full password complexity enforced (length, uppercase, digit, special
   character) — `app/core/validation.py`, applied to `change-password`.
6. ✅ `organisation_id` and `last_login_at` are on `users` from the start
   (`app/models/user.py`). Multi-tenant *isolation* (scoping queries by
   org) is not implemented yet — that's RBAC/data-access work, not
   authentication's job.
7. ✅ No `role` claim in the JWT at all — the access token carries only
   `sub` (user id) and `org` (organisation id).
8. ⏸ Mobile secure token storage — deferred, no mobile app exists in this
   repo yet.
9. ⏸ Mobile change-password parity — deferred, same reason.
10. ⏸ Unify frontend/mobile refresh-interceptor logic — deferred until a
    frontend exists to write one.
11. N/A — there's one seed script (`scripts/seed_admin.py`), not three, so
    there's nothing to consolidate. It uses `getpass` throughout.
12. ✅ Test suite added — `backend/tests/test_auth.py` covers login
    (success, wrong password, unknown user, inactive user, lockout),
    refresh rotation and replay rejection, logout revocation, and
    change-password (wrong current password, weak new password, and the
    full success path including old-session/old-password invalidation.
    12 tests, all passing.

Also decided along the way, not in the original list: RBAC's `role`
column and any user profile fields (department, phone, avatar, manager)
are deliberately **not** on this `users` table — see
[`../modules/authentication.md`](../modules/authentication.md)'s note on
keeping identity and authorization schema-separated from day one, per
finding #6 above.
