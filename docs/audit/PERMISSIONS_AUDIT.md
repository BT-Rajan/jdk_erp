# Permissions / Access Scope Audit — `jdk_clean`

Phase 0 audit of the scope/permission-resolution layer, per
[`../ROADMAP.md`](../ROADMAP.md) and the spec in
[`../modules/permissions.md`](../modules/permissions.md). The evidence
here was gathered auditing Teams and RBAC — see
[`TEAMS_AUDIT.md`](TEAMS_AUDIT.md) and [`RBAC_AUDIT.md`](RBAC_AUDIT.md)
— and is consolidated rather than re-derived, with one addition: a
closer look at `has_page_access()`'s actual scope-resolution logic,
which the earlier audits didn't need to dig into.

## Verdict

**Reuse the shape (deny-by-default, module×action→level), not the
implementation.** `jdk_clean`'s `department_permissions` +
`has_page_access()` (`app/core/permissions.py:134+`) is structurally the
same idea this module specifies — a lookup table mapping a scope key to
an access level, consulted centrally rather than reinvented per module.
Two things about its implementation don't carry forward.

## What's reused

The core resolution shape: no row for a given key means "none" (deny by
default), a specific level (`read`/`write` there; `own`/`team`/`all`
here) is granted per row, and there's exactly one function callers go
through (`has_page_access()`) rather than each endpoint rolling its own
check — matching [`permissions.md`](../modules/permissions.md) §11's
"modules do not reinvent authorization."

## What's not reused, and why

**`PAGE_KEYS` is a hardcoded Python tuple** (`permissions.py:48-70`) that
every new page must be added to by editing code and shipping a deploy —
`PAGE_KEY_LABELS`'s matching `assert` (`permissions.py:98-100`) exists
specifically to catch the two drifting apart. `module_key`/`action` in
this project are plain strings in a database row instead: §2 says the
real catalog is defined "per module based on actual business workflows,"
i.e. arrives with each future module's own code, so registering one
should be a data change (insert a permission row), not a second
mandatory code change on top of building the module itself.

**Scope resolution is keyed on a single `department_id`.**
`same_department()`/`has_page_access()` (`permissions.py:120-121`, `134+`)
assume one department per user — already identified as incorrect in
[`RBAC_AUDIT.md`](RBAC_AUDIT.md) once membership became many-to-many.
Not reusable regardless of the `PAGE_KEYS` question above:
`get_user_team_ids()` (this module) returns the user's *whole* team set,
and `TEAM` scope means the union across it, per
[`permissions.md`](../modules/permissions.md) §3/§5.

**Department itself carries the permission row's scope key.**
`department_permissions.department_id` makes the department table double
as an authorization axis (already the central finding in
[`TEAMS_AUDIT.md`](TEAMS_AUDIT.md)). This module's `role_permissions`/
`user_permissions` reference `Team` only indirectly, through
`get_user_team_ids()` at query time — `Team` itself stays exactly what
[`teams.md`](../modules/teams.md) says it is, grouping only.

**No per-user override mechanism.** `jdk_clean` has no equivalent of
this module's `user_permissions` — access is entirely determined by
`role` + `department_id`, so there's no way to give one Team Member
`TEAM` scope on a specific module without changing their role or
department for everyone else in it. [`permissions.md`](../modules/permissions.md)
§5/§6 explicitly need this (Ravi's per-module Accounts exception); a
second small table is added for it rather than overloading the
role-based one.
