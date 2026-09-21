# Teams / Departments Audit — `jdk_clean`

Phase 0 audit of the team/department layer, per
[`../ROADMAP.md`](../ROADMAP.md) and the spec in
[`../modules/teams.md`](../modules/teams.md).

## Verdict

**Partial reuse.** Unlike Organisation (nothing existed) and unlike Users
(the identity shape ported forward as-is), `jdk_clean` has a real
`Department` entity with a genuinely good minimal shape — but it is also
the clearest example in this codebase of exactly the anti-pattern this
module is named to avoid: a department that doubles as a permission
system.

## What's there

`departments` table (`backend/schema.sql:43-54`), ORM model
`backend/app/models/department.py:9-27`: `id`, `code` (unique), `name`,
`status` (`active`/`inactive`), soft-delete (`deleted_at`), audit
timestamps. Four rows seeded by default: sales, procurement, warehouse,
production (`schema.sql:56-61`). This shape — id, code, name,
active/inactive, timestamps — is almost exactly
[`teams.md`](../modules/teams.md) §2's minimal record, and is reused
directly (adding only `organisation_id`, since `jdk_clean` has no
organisation concept at all — see
[`ORGANISATION_AUDIT.md`](ORGANISATION_AUDIT.md)).

`users.department_id` (`schema.sql:79`, nullable, FK to `departments.id`)
is the one-user-one-department relationship this module's §3 also calls
for. Reused directly as `users.team_id`.

## What's explicitly not reused, and why

**Department is the row axis of a page-permission matrix.** A second
table, `department_permissions` (`schema.sql:1492-1501`), stores
`(department_id, page_key) → access_level`, and
`backend/app/core/permissions.py:1-33,134+` consults it on effectively
every protected request for the `department_head`/`team_member`
(and legacy `staff`/`manager`) roles: "governed by
department_permissions, keyed on their own department_id... A
department/page combination with no row means 'none' — deny by default."
This is not team membership determining scope (§5's "Team = scope, Role =
authority") — it's the department itself carrying page-level
authorization data, department_permissions.py:1's own words: "a
configurable department x page matrix." That is precisely what this
module's title says not to become. It is not reused. When RBAC (the next
phase) needs a scope × permission structure, it will be built against
RBAC's own role/permission tables, referencing `Team` only as a foreign
key the way any other module would, not by re-growing a
`team_permissions` table.

**`users.manager_id`.** A self-referential FK (`schema.sql:83`, "Which
Manager this user... reports to in the org chart") — a bespoke reporting
hierarchy that exists *alongside* role and department, not derived from
them. [`teams.md`](../modules/teams.md) §4 explicitly rejects this
pattern: a manager's authority over a team should read as `role =
Manager` + `team = Sales`, not a separate hierarchy column that can drift
from role/team and has to be maintained independently (`jdk_clean`'s own
migration history shows this: `manager_id` needed its own migration,
separate from the role and department columns it overlaps with in
meaning). Not reused. If JDK ever needs a literal org chart independent
of role/team, that's a deliberate, separate feature — not a default.

**`department_head` vs `team_member` role distinction.** Two of the six
values in `users.role`'s enum (`schema.sql:89`) are department-specific
role names. Role granularity is RBAC's decision, not this module's — noted
here only so RBAC's own audit doesn't need to rediscover it.

## Scope decisions

Same reasoning as the two prior modules' admin APIs (see
[`ORGANISATION_AUDIT.md`](ORGANISATION_AUDIT.md) and
[`USERS_AUDIT.md`](USERS_AUDIT.md)): no create/edit/deactivate/assign
API for teams yet — that needs an "authorised Admin," which RBAC hasn't
defined. `scripts/seed_admin.py` is extended to optionally create/assign
a team, the same bootstrap-only path already used for organisations and
users.
