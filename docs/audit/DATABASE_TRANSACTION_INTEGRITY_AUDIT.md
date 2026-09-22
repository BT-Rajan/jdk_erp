# Database + Transaction Integrity Audit

Verdict on `docs/modules/database_transaction_integrity.md` against the
existing schema (`app/models/`), migrations (`backend/migrations/versions/`),
services (`app/services/`) and routers (`app/api/`). No Sales/Finance/
Products/Materials tables exist yet, so this audit covers the seven
tables that do exist (`organisations`, `users`, `teams`,
`role_permissions`, `user_permissions`, `user_teams`, `refresh_tokens`,
`audit_events`) and the transaction boundaries already in code.

## Already present

- **One supported production database.** `pymysql` + `mysql+pymysql://`
  is the documented production URL (`.env.example`); SQLite is a
  zero-setup dev/test convenience, not a second supported production
  database.
- **Consistent naming, clear PKs.** Every table is plural snake_case
  with an `id` integer primary key; columns are snake_case throughout.
- **NOT NULL / UNIQUE where it matters.** `users.email`/`username` are
  unique + not null; every join/scope table has a composite
  `UniqueConstraint` matching its actual business-uniqueness rule
  (`uq_teams_organisation_id_name`, `uq_role_permissions_scope_key`,
  `uq_user_permissions_scope_key`, `uq_user_teams_user_id_team_id`).
- **No formatted-string business data, no unnecessary JSON.** Every
  column is a real relational type; `Organisation.currency` is an ISO
  code string (configuration), not a formatted amount; no JSON column
  exists anywhere.
- **Database constraints as the final protection, not just app code.**
  `app/core/error_handlers.py` already has a dedicated
  `IntegrityError` → `409 CONFLICT` handler distinct from the generic
  500 handler -- exactly "application validation gives good feedback,
  database constraints provide the final protection" already wired
  end-to-end (verified by `permissions.py`'s upsert-under-race falling
  through to this handler rather than a raw 500).
- **Deactivation over deletion for master/business records.** No route
  or service hard-deletes an `Organisation`, `User`, or `Team` --
  every one of those is `is_active`-flag-driven. Only pure join/grant
  rows (`UserTeam`, `RolePermission`, `UserPermission`) are ever
  hard-deleted, which is correct: they have no standalone history value.
- **Versioned, tracked migrations.** Every schema change already goes
  through Alembic (`backend/migrations/versions/0001`-`0009` before
  this audit); this project has never hand-edited a schema.
- **Business change + audit record committed together.** Every mutating
  route/service that calls `audit_service.log_event` (`teams.py`,
  `users.py`, `auth_service.change_password`/`logout`) already builds
  the audit row uncommitted and commits it in the exact same
  `db.commit()` as the business change -- `audit_service.log_event`'s
  own docstring states this is deliberate. This already satisfies #10
  everywhere except the two places fixed below.
- **Database-level atomic update, not read-modify-write, for bulk
  revocation.** `auth_service.revoke_all_sessions` issues a single
  `UPDATE ... WHERE user_id = ? AND revoked = false`, not a per-row
  read-then-write loop.
- **No triggers, stored procedures, or ON UPDATE CASCADE anywhere.**
  Every migration is plain DDL; the only automatic DB behaviour is the
  `ON DELETE` behaviour this audit makes explicit (see below) --
  nothing implicit.

## Genuine gaps found and fixed

1. **SQLite silently ignored every `ForeignKey()` in these models.**
   Verified directly: without `PRAGMA foreign_keys=ON`, deleting an
   `Organisation` row that still had a `User` referencing it succeeded
   with no error. MySQL (this project's one production database)
   enforces FKs by default, so dev/test was quietly exercising weaker
   guarantees than production. Fixed in `app/core/database.py` with a
   `connect`-event listener scoped to this project's own `engine`
   object, gated to only fire when `DATABASE_URL` is sqlite.
2. **No foreign key anywhere declared an explicit `ON DELETE` behaviour**
   (#2's literal "define explicit delete behaviour"). Every FK relied
   on each database's own implicit default instead of a stated,
   reviewable choice. Migration `0010` makes all eleven FKs explicit,
   chosen per the actual semantics of each relationship:
   - `organisation_id` (all four organisation-scoped tables) → `RESTRICT`:
     organisations are deactivated, never deleted, but the rule is
     stated rather than assumed.
   - `audit_events.organisation_id` → `RESTRICT`: an audit trail is
     exactly the "important business record" #2 says must not be
     orphaned.
   - `refresh_tokens.user_id`, `user_teams.user_id`/`team_id`,
     `user_permissions.user_id` → `CASCADE`: pure session/membership/
     grant rows with no standalone value once their owner is gone.
   - `audit_events.user_id`/`actor_user_id` → `SET NULL`: the audit row
     itself must outlive the user it references (these columns were
     already nullable for exactly the "actor not resolved" case).
   Also added a `naming_convention` on `Base.metadata` so every future
   constraint gets a deterministic, addressable name -- the mechanism
   that made this migration possible at all, since several existing FKs
   reflected with no name (SQLite never named them).
3. **Pre-existing schema drift**, unrelated to this phase's changes:
   `audit_events.action` was still `VARCHAR(20)` in the actual schema
   (from `0001`'s original `event_type` column) while the ORM model has
   declared `String(30)` since the `0008` rename -- `alembic check`
   (added to this project's own verification step) caught it. Harmless
   on SQLite (no length enforcement) but would silently truncate or
   reject on MySQL. Fixed in migration `0011`.
4. **Login/refresh were not one transaction.** `auth_service.login()`
   committed `last_login_at` + the `login_success` audit event, *then*
   issued the refresh token in a second, separate commit; `refresh()`
   committed the old token's revocation, *then* issued the replacement
   in a second commit. Either partial-failure left a false record: a
   committed "login succeeded" audit event for a login the caller never
   received tokens for, or a burned refresh token with no replacement
   ever issued. Fixed by making `_issue_tokens` not commit -- each
   caller now commits exactly once for the whole logical operation
   (#5/#6/#9). Regression tests
   (`tests/test_database_integrity.py::test_login_success_is_atomic_with_token_issuance`,
   `::test_refresh_does_not_revoke_the_old_token_if_reissue_fails`)
   force a failure between the two former commits and assert nothing
   partially persisted.
5. **The login-lockout query had no matching index.**
   `auth_service.login()` runs
   `WHERE action = ? AND username_attempted = ? AND created_at >= ?`
   on every single login attempt (success or failure), but
   `username_attempted` only had a standalone index. Migration `0012`
   replaces it with a composite
   `(username_attempted, action, created_at)` index matching this exact
   query shape, and drops the now-redundant standalone one (its leading
   column is a prefix of the new composite).

## Reviewed, not changed

- **`users.organisation_id` carries both a standalone index (from
  `OrganisationScopedMixin`) and a composite
  `(organisation_id, is_active)` index.** The standalone one is a
  redundant prefix of the composite. Left as-is: it's a few KB of
  write overhead on a small table, not a correctness issue, and the
  mixin is shared by three other tables that have no such composite --
  removing the mixin's index would require per-subclass overrides for
  a marginal gain. Noted here per #3's "review indexes against actual
  query patterns" rather than silently ignored.
- **The login-lockout *count* itself is a read-then-decide check, not a
  single atomic update** (`recent_failures = count(...); if
  recent_failures >= threshold: ...`). Under concurrent brute-force
  attempts within the same window, several requests could all read a
  count below the threshold before any of their own failure events
  commit, allowing a small overshoot past the configured limit. This is
  architecturally different from #7's stock-quantity example (there is
  no single row being decremented -- the "counter" is a set of
  independent audit rows by design, see `AuditEvent`'s own docstring),
  and a lockout threshold is a rate-limiting deterrent, not a
  correctness-critical balance. Adding real locking here (e.g. a
  dedicated, row-locked counter) would be exactly the "sophisticated
  transaction system" this module's own instructions say not to build,
  for a security margin, not a data-integrity one. Documented as an
  accepted approximation rather than fixed.
- **No `DECIMAL`/`Numeric` columns exist anywhere.** #1's "correct
  `DECIMAL` types for money/quantities" has no table to apply to yet --
  no Sales/Finance/Products/Materials module exists. When one is built,
  it must use `Numeric`/`DECIMAL`, never `Float`, for any money or
  quantity column, and should reuse `app/core/currency.round_currency`
  (docs/modules/common_validation.md #4) for rounding rather than
  inventing its own.
- **No atomic stock/quantity update exists to fix**, for the same
  reason -- no inventory table exists yet. #7's principle
  (database-level atomic/locked updates, not read-calculate-write) is
  documented in `docs/modules/database_transaction_integrity.md` for
  whichever future module first needs it.

## What's added

| Area | File |
| --- | --- |
| SQLite FK enforcement + naming convention | `app/core/database.py` |
| Explicit `ON DELETE` on every FK | `app/models/{mixins,refresh_token,user_team,user_permission,audit_event}.py`, migration `0010` |
| Fix `audit_events.action` width drift | migration `0011` |
| Login-lockout composite index | `app/models/audit_event.py`, migration `0012` |
| One-commit login/refresh | `app/services/auth_service.py` |
| Tests | `backend/tests/test_database_integrity.py` |

## Deliberately not built now

No generic transaction framework, no distributed-transaction handling,
no ORM-level soft-delete abstraction, and no atomic stock/quantity
helper -- there is no caller for any of these yet. Whichever module
first needs an atomic quantity update (#7) or a multi-table business
transaction shaped like the spec's own order example (#5) should follow
this audit's login/refresh fix as the pattern: validate before opening
the transaction, apply every authoritative change and the audit record
inside it, commit exactly once, and never call a slow external
operation (email, QR generation, file processing) from inside that
transaction.
