# JDK Roles & RBAC

Fifth foundation layer, after [`authentication.md`](authentication.md),
[`organisation.md`](organisation.md), [`users.md`](users.md) and
[`teams.md`](teams.md), per [`../ROADMAP.md`](../ROADMAP.md) Phase 1.
Defines precisely what Super Admin, Admin, Manager and Team Member can
do — one level deep, no complicated permission engine.

## 1. The corrected team-membership model

A user can belong to **multiple** teams/departments, not one:

```text
Organisation
    │
    ├── Users
    │     └── User → multiple Teams
    │
    └── Teams
          ├── Sales
          ├── Accounts
          ├── Production
          └── ...
```

Still one level deep — no nested departments, divisions, or sub-teams.
This supersedes [`teams.md`](teams.md) §3's original "one user → one
team" and [`users.md`](users.md) §5's matching diagram.

## 2. Four concepts, kept separate

- **Role** = overall authority (Super Admin, Admin, Manager, Team
  Member).
- **Team membership** = which departments the user participates in.
- **Record ownership** = whose specific work/record it is.
- **Module permissions** = what the user can do within that team, once a
  module (Sales, Production, ...) exists to define it.

Example:

```text
Ravi
Role: Team Member
Teams: Sales, Accounts
```

Ravi can work in both Sales and Accounts, but his access in each area is
still controlled by his role and that module's own rules — team
membership is scope, not a grant of unrestricted access.

```text
A Manager could be:
Role: Manager
Teams: Sales, Accounts
```

They have manager-level scope in both assigned teams.

## 3. No "primary team"

Deliberately not modelled, unless the business needs reporting around
it. If a user belongs to Sales + Accounts + Production, those are simply
their active team memberships — no ranking or "main" one among them.

## 4. Administration

Only Super Admin / an authorised Admin can:

- Add a user to a team.
- Remove a user from a team.
- Change a user's role.
- View a user's team memberships.

A user cannot add themselves to another team.

## 5. Database

A proper many-to-many relationship:

```text
users
  id
  organisation_id
  role
  ...

teams
  id
  organisation_id
  name
  ...

user_teams
  user_id
  team_id
```

Unique constraint on `(user_id, team_id)` — prevents duplicate
membership.

## 6. Access model

The `OWN / TEAM / ALL` model still works; `TEAM` now means *any* team the
user is assigned to, subject to the module's own permissions:

```text
User
 ├── Role: Manager
 ├── Sales
 └── Accounts
```

A Manager can have team scope across both Sales and Accounts, but being a
member of a team does not automatically grant unrestricted access to
every record in it — the module's authorization rules still determine
what's actually viewable/editable. This model has no consumer yet (no
business module exists to scope), so it's documented here as the
contract future modules build against, not implemented as a standalone
mechanism with nothing to call it (Principle 5: no abstraction without a
real user).

## 7. Updated principle

Users may belong to multiple teams/departments. Super Admin or an
authorised Admin controls team membership. Role defines authority; team
membership defines organisational scope; record ownership defines
individual work access. Still one level deep:

```text
Organisation → Teams ↔ Users
```

No nested departments, divisions, sub-teams, or organisational trees.

## Implementation approach

Per [`../ENGINEERING_PRINCIPLES.md`](../ENGINEERING_PRINCIPLES.md) §16
and the roadmap's audit-first rule: see
[`../audit/RBAC_AUDIT.md`](../audit/RBAC_AUDIT.md).

**The team-membership correction came first, before any RBAC code**,
since building role-gated membership endpoints against the old
one-`team_id`-column model would have meant redoing them the moment §1's
correction landed. `users.team_id` is removed; a `user_teams` table
(user_id, team_id, unique together) replaces it.

**What's implemented:**

- `User.role` — one of `super_admin`, `admin`, `manager`, `team_member`.
  No separate `roles` table: this is a small, fixed set (§2 names
  exactly four), not data an organisation configures — a table would be
  an abstraction with nothing that needs it yet (same reasoning as §6's
  deferred access model).
- `user_teams` (§5), with team-membership management:
  `POST /api/teams/{team_id}/members`, `DELETE
  /api/teams/{team_id}/members/{user_id}` — both admin-gated (`super_admin`
  or `admin` only), both re-checked against the caller's own
  organisation (an Admin from Organisation A cannot touch Organisation
  B's teams or users — [`teams.md`](teams.md) §9).
- `PATCH /api/users/{user_id}/role` — admin-gated role change, same
  organisation-boundary check.
- "View a user's team memberships" (§4) piggybacks on the existing,
  already-ungated `GET /api/users/{id}` (now returning `team_ids`) and
  `GET /api/users?team_id=...` — no new endpoint needed for a read that
  was already safe to expose (Principle 5).
- A user cannot add themselves to a team or change their own role (§4):
  true by construction — no self-service endpoint touches `role` or
  `user_teams`, and the admin-gated ones reject a non-admin caller
  regardless of whose membership they're trying to change.

**Deliberately not built:**

- The `OWN/TEAM/ALL` module-permission engine (§6) — no module exists
  yet to consult it. It's specified here so the first module that needs
  it (Phase 2+) implements it against a settled contract instead of
  inventing its own.
- Create/edit/deactivate for Organisation, Team, and User themselves.
  This phase only builds what §4 explicitly asks for (membership + role).
  The three prior modules' own deferred admin APIs (create an
  organisation, create/deactivate a user, create/deactivate a team) are
  a separate, later piece of work now that a role gate exists to build
  them against — not assumed to be in scope here just because the gate
  now exists.
- A cross-organisation "Super Admin" capability (e.g. an API to create a
  new organisation). [`organisation.md`](organisation.md) §6 describes
  Super Admin as able to create organisations, which implies operating
  *above* any single organisation. `super_admin` exists as a role value
  so that distinction is representable, but today it behaves identically
  to `admin` within its own organisation — no endpoint yet does anything
  a `super_admin` can do that an `admin` can't. Building real
  cross-organisation capability is deferred until it's actually asked
  for, rather than guessed at now.
