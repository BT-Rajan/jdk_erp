# Roles & RBAC Audit — `jdk_clean`

Phase 0 audit of role/permission logic, per [`../ROADMAP.md`](../ROADMAP.md)
and the spec in [`../modules/roles_rbac.md`](../modules/roles_rbac.md).
Most of the evidence was already gathered auditing Authentication and
Teams — this consolidates it rather than re-deriving it, and adds one
focused pass over `app/core/permissions.py` specifically for role/scope
logic.

## Verdict

**Reuse the concept of a small, fixed role set. Do not reuse the
page-permission matrix, the legacy role aliasing, or the one-department
assumption baked into it.**

## What's there

`users.role` is a six-value enum (`schema.sql:89`): `admin`, `manager`,
`staff`, `viewer`, `department_head`, `team_member`. Two of those,
`manager`/`staff`, are explicitly legacy synonyms for
`department_head`/`team_member`, kept "for backward compatibility with
existing rows" (`app/models/user.py:57-68`,
`migrations/2026-10-02_add_department_head_team_member_roles.sql`).
`app/core/permissions.py:103-117` defines `is_admin`, `is_department_head`,
`is_team_member` as simple `user.role ==` checks — a plain role check,
not a separate roles table, which is a reasonable, minimal pattern this
project's four-role set (Super Admin, Admin, Manager, Team Member) reuses
the *shape* of, without the legacy aliases (there's no prior data here to
be backward-compatible with).

## What's not reused, and why

**The department × page permission matrix.**
`department_permissions` (`schema.sql:1492-1501`) and
`has_page_access()` (`app/core/permissions.py:134+`) implement exactly
the `OWN/TEAM/ALL`-style module-permission concept
[`roles_rbac.md`](../modules/roles_rbac.md) §6 describes — but hardcoded
to one specific shape (a department-keyed page/level grid) for a fixed
list of pages (`PAGE_KEYS`, `permissions.py:48-70`) that don't exist in
this project yet (Sales, Production, etc. are Phase 2/3). Copying this
table now would mean building permission data for modules that aren't
built, guessing at their shape ahead of time. §6 is deliberately left as
a documented contract instead, for the first real module to implement
against.

**`is_team_member`'s dual-role check.** `user.role in ("team_member",
"staff")` (`permissions.py:111-117`) exists only because of the legacy
enum values noted above. Nothing to carry forward — this project's role
column starts with exactly the four current values, no aliases.

**The one-department-per-user assumption.** `same_department()`
(`permissions.py:120-121`) and every department_permissions lookup key on
a single `user.department_id`. This is the same assumption
[`ORGANISATION_AUDIT.md`](TEAMS_AUDIT.md) and
[`roles_rbac.md`](../modules/roles_rbac.md) §1 explicitly overturn: a
user now has *many* team memberships, so any future scope check is
"is any of the user's teams the record's team," not a single equality.
Not reusable as-is regardless of the matrix question above.

**`can_access_owned_or_assigned_record()`** (`permissions.py:124-131`) —
a `created_by`/`assigned_to` ownership check — is a reasonable pattern
matching [`roles_rbac.md`](../modules/roles_rbac.md) §2's "record
ownership" concept. Worth reusing in *shape* once a module has
`created_by`/`assigned_to` fields to check (none does yet); not
implemented now for the same reason as §6 — no caller.

## Scope decisions for this phase

Team-membership management (add/remove, role change) is gated by role
for the first time in this project — everything before this phase was
either ungated (read-only directory endpoints) or gated only by identity
(a user acting on their own record). Organisation/Team/User's own
create/edit/deactivate admin APIs, deferred across the last three
modules specifically *because* no role gate existed, are **not**
automatically in scope just because one now does — see
[`roles_rbac.md`](../modules/roles_rbac.md)'s implementation section for
why that's tracked as separate, later work rather than folded in here.
