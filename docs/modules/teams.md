# JDK Teams / Departments

Fourth foundation layer, after
[`authentication.md`](authentication.md), [`organisation.md`](organisation.md)
and [`users.md`](users.md), per [`../ROADMAP.md`](../ROADMAP.md) Phase 1.
Organisational grouping and, later, a manager's visibility scope — not
another permission system.

> **Revision:** §3 originally read "one user → one team." That's
> superseded — see [`roles_rbac.md`](roles_rbac.md), which corrects it to
> a many-to-many membership (a user can belong to several teams; no
> "primary team" concept). §3, §10, and §11 below are updated to match;
> the rest of this document (§1, §2, §4-9, §12) is unaffected, since the
> correction is about *how many* teams a user belongs to, not what a team
> is or what it's for.

## 1. Purpose

A Team/Department answers: which part of the organisation does this user
work in?

```text
Organisation
    ↓
Team / Department
    ↓
Users
```

One level deep only.

## 2. Team record

Kept minimal: Team/Department ID, Organisation ID, Name, Code (if
useful), Description (optional), Active/inactive, Created/updated
timestamps.

No hierarchy such as `Department → Division → Section → Sub-team`. Not
needed.

## 3. User relationship

**A user may belong to multiple teams.** A team can have many users; a
user can have many teams. No "primary team" — see
[`roles_rbac.md`](roles_rbac.md) for the full reasoning.

```text
Sales
 ├── Manager
 ├── Salesman
 ├── Salesman
 └── Salesman
```

Role and team remain separate concepts — a person can be `Manager +
Sales` or `Team Member + Sales`, and can hold that role across more than
one team at once (e.g. `Team Member` in both `Sales` and `Accounts`).

## 4. Team manager

No separate "manager hierarchy" system. `Role = Manager` + `Team = Sales`
already tells the system this user manages/has visibility over the Sales
team. If the business later needs multiple managers or special reporting
structures, add that deliberately, not as a default.

## 5. Team access

Team membership determines organisational scope, not per-record access:

```text
Sales Team
 ├── Manager A
 ├── Salesman B
 └── Salesman C
```

Manager A can access the team's permitted data. Salesman B does not
automatically see Salesman C's restricted records merely because they
share a team — that distinction belongs to RBAC + module-level ownership
rules.

So: **Team = scope, Role = authority, Record ownership = who owns the
work.**

## 6. Team administration

An authorised Admin should be able to create/edit/activate/deactivate a
team, add/remove/move users, and view team members. Don't delete teams
with historical data — deactivate instead.

## 7. Moving a user

When a user moves teams, their current team access changes immediately,
but existing quotations, orders, and audit records stay exactly as they
were. Never rewrite historical records because organisational membership
changed.

## 8. Team deletion

Prefer deactivating a team over hard delete. Don't allow deactivating a
team that still has active users assigned, unless there's an explicit
system-level procedure for it.

## 9. Security

All team operations are server-authorized. A user must not be able to
manipulate `team_id`, `organisation_id`, or `role` through a modified API
request. An Admin from Organisation A must never manage Organisation B's
teams.

## 10. Performance

```text
teams
    organisation_id
    id
    name
    status

users
    organisation_id

user_teams
    user_id
    team_id
```

A proper many-to-many `user_teams` table with a unique constraint on
`(user_id, team_id)` — see [`roles_rbac.md`](roles_rbac.md) §Database.
Index `organisation_id` on `teams`, and both `user_id`/`team_id` on
`user_teams`.

## 11. Acceptance tests

1. Admin creates a team.
2. Admin assigns users to the team.
3. A user can belong to multiple teams at once.
4. A user's team memberships can be changed (added/removed) by an admin.
5. Team membership changes immediately affect current access scope.
6. Historical records remain unchanged.
7. Inactive team cannot receive new users.
8. Team cannot cross organisation boundaries.
9. Users cannot change their own team.
10. A Team Member cannot access another member's restricted work simply
    because they share a team.
11. Manager can later use team membership as their department scope.
12. No nested teams/departments are introduced.

## Foundation now

```text
ORGANISATION
     │
     ├── USERS
     │    ├── Authentication
     │    └── Role
     │
     └── TEAMS / DEPARTMENTS
              │
              └── USERS
```

Next: Roles & RBAC — precisely what Super Admin, Admin, Manager and Team
Member can do, one level deep, no complicated permission engine.

## Implementation approach

Per [`../ENGINEERING_PRINCIPLES.md`](../ENGINEERING_PRINCIPLES.md) §16
and the roadmap's audit-first rule: see
[`../audit/TEAMS_AUDIT.md`](../audit/TEAMS_AUDIT.md). Unlike
Organisation, `jdk_clean` *does* have a real equivalent (`Department`) —
its minimal shape (id, code, name, status) is reused; two things about it
are deliberately **not** reused, both because they contradict this
module's own opening line ("should not become another permission
system"):

- `jdk_clean` wired `Department` directly into a page-permission matrix
  (`department_permissions` — a department × page × access-level table
  consulted on every request). Department there *is* a permission system.
  This project's `Team` carries no such table and is not consulted by any
  authorization check — that coupling is RBAC's decision to make later,
  against its own role/permission tables, not something Team pre-empts.
- `jdk_clean` gave `User` a self-referential `manager_id` — a bespoke
  reporting-line hierarchy alongside role and department. §4 explicitly
  rejects this: a manager's scope is `role = Manager` + `team`, not a
  separate hierarchy column. Not carried forward.

**Deferred to RBAC**, consistent with every prior module's admin API
(Organisation, Users): create/edit/activate/deactivate a team and
add/remove/move a user between teams all require an "authorised Admin,"
which doesn't exist until RBAC defines it. `scripts/seed_admin.py` can
optionally create/assign a team when creating a user, same as it already
does for organisations — that remains the only way to set one up until
RBAC lands. Acceptance criteria 1, 2, 4, 5, 7, 9 (enforcement), 10, 11 are
consequently deferred; 9 (a user can't change their own team) and 12 (no
nesting) already hold today, by construction — there's no endpoint that
touches `team_id` at all, and no parent-team column exists.

**Implemented now:**

- The `teams` table: organisation-scoped, name unique within the
  organisation (not globally — unlike usernames, team names carry no
  login-disambiguation problem, so per-organisation uniqueness is exactly
  what §2 calls for with no trade-off needed), code unique within the
  organisation when provided.
- `GET /api/teams`, `GET /api/teams/{id}` — organisation-scoped, same
  shape and same cross-organisation 404 behaviour as the Users directory.
- `GET /api/users?team_id=...` — reuses the existing directory endpoint
  (Principle 5: reuse before creating) rather than adding a separate
  "team members" endpoint, satisfying acceptance criterion 6's "view team
  members" without new surface area.

**Corrected in the RBAC phase, before that phase's own work started**
(see [`roles_rbac.md`](roles_rbac.md)): the original implementation gave
`User` a single nullable `team_id` column (one team per user). That was
replaced by a `user_teams` many-to-many table before Role/RBAC was built
on top of it, since building RBAC against the one-team assumption would
have meant redoing it immediately after. The membership-management
endpoints (add/remove a user from a team, change role) are implemented in
the RBAC phase, since they need the admin-role gate that phase defines.
