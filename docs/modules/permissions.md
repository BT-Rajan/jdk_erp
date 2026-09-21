# JDK Permissions / Access Scope

Sixth foundation layer, after [`authentication.md`](authentication.md),
[`organisation.md`](organisation.md), [`users.md`](users.md),
[`teams.md`](teams.md) and [`roles_rbac.md`](roles_rbac.md), per
[`../ROADMAP.md`](../ROADMAP.md) Phase 1. The layer that ties everything
together — kept central, predictable and small.

## 1. Separate the concepts

```text
Authentication → Who are you?
Role           → What authority do you have?
Team           → Where do you work?
Ownership      → Which specific records are yours?
```

**Permission** combines these to determine whether an action is allowed.

## 2. Keep permissions module-level

Don't create hundreds of granular permissions. Use meaningful ERP
capabilities:

```text
Sales
  View
  Create
  Edit
  Approve

Inventory
  View
  Create
  Adjust

Production
  View
  Create
  Execute

Finance
  View
  Create
  Approve
```

The exact permissions are defined **per module based on actual business
workflows**, not invented globally in advance.

## 3. Scope

Every permission has an access scope: `ALL`, `TEAM`, `OWN`.

- **ALL** — access all permitted records within the organisation.
- **TEAM** — access records belonging to the user's assigned teams.
  Because users can belong to multiple teams, `TEAM` means the union of
  the user's relevant team scopes.
- **OWN** — access only records the user owns/is assigned to.

## 4. Role gives the default authority

| Role        | Typical scope           |
| ----------- | ------------------------ |
| Super Admin | ALL                       |
| Admin       | ALL within organisation   |
| Manager     | TEAM                      |
| Team Member | OWN                       |

Not a hard-coded absolute rule — a module can grant a Team Member `TEAM`
access for a particular operational task if the business requires it.
**Role + permission + scope are centrally evaluated.**

## 5. Multi-team example

```text
Ravi
Role: Team Member
Teams: Sales, Accounts

Sales    → View = OWN
Accounts → View = OWN
```

Ravi sees only his own permitted work in both modules. If an Admin gives
him `Accounts → View = TEAM`, he can see permitted Accounts team
records, without automatically gaining broader Sales access. Cleaner
than a global "Accounts access" flag.

## 6. Manager example

```text
Ravi
Role: Manager
Teams: Sales, Accounts

Sales:    View → TEAM, Edit → TEAM
Accounts: View → TEAM
```

Ravi manages Sales team work while having only the permitted Accounts
access. **Role alone doesn't need to determine every module permission.**

## 7. Record ownership

A record retains its owner/assignee:

```text
Quotation
 ├── organisation_id
 ├── team_id
 └── owner_user_id
```

Authorization evaluates, in order:

```text
Is organisation correct?
        ↓
Does user have permission?
        ↓
Is record within permitted team?
        ↓
Is record owned/assigned to user if scope = OWN?
```

Particularly important for Sales.

## 8. Cross-team records

Some records naturally belong to more than one department:

```text
Sales Order → Sales → Production → Accounts
```

Don't duplicate the order into three systems — the Order remains **one
record**. Each module gets access according to its own permission and
workflow. Critical for ERP data integrity.

## 9. Who manages permissions?

- **Super Admin** — can manage everything.
- **Admin** — can assign users to teams and assign permitted
  roles/access within the organisation.
- **Manager** — cannot grant themselves or others higher privileges.
- **Team Member** — cannot manage permissions.

Avoid letting ordinary users create arbitrary permission combinations.

## 10. No custom permission engine initially

Not building: nested permissions, permission inheritance, policy
expressions, conditional rules, custom scripting, attribute-based access
control, or dozens of boolean flags. Instead:

```text
User → Role → Permission → Scope → Organisation + Team + Ownership
```

Simple enough for every developer to understand.

## 11. Central authorization service

Every module uses the same authorization mechanism. Conceptually:

```text
can(user, action, resource)
```

The authorization layer determines whether it's allowed, and at what
scope (`ALL`/`TEAM`/`OWN`). **Modules do not reinvent authorization.**

## 12. Performance

- Avoid querying permissions repeatedly.
- Keep permission structures small.
- Index organisation/team/user relationships.
- Scope database queries directly (`WHERE organisation_id = ? AND
  team_id IN (...)`) rather than loading everything and filtering in
  application code.
- Reuse the authenticated user context.

## 13. Acceptance tests

1. User cannot access another organisation's data.
2. User only receives permissions assigned to their role/access.
3. Multi-team user can access all authorised teams.
4. Removing a team immediately removes that team's access.
5. `OWN` cannot access another user's record.
6. `TEAM` can access permitted records within assigned teams.
7. `ALL` stays inside the organisation unless Super Admin explicitly has
   system-wide access.
8. Direct API/URL manipulation cannot bypass scope.
9. Users cannot grant themselves permissions.
10. Managers cannot grant Admin/Super Admin access.
11. Cross-module records remain one authoritative record.
12. Changing team membership does not change historical ownership.

## The JDK access model

```text
                     ORGANISATION
                          │
                     ┌────┴────┐
                     │         │
                   USERS     TEAMS
                     │         │
                     └────┬────┘
                          │
                       ROLE
                          │
                     PERMISSIONS
                          │
                       SCOPE
                    ┌─────┼─────┐
                   OWN   TEAM   ALL
                    │     │      │
                    └─────┴──────┘
                          │
                    RECORD OWNERSHIP
                          │
                     ERP MODULES
```

**Not purely role-based.** Role provides the baseline authority; Admin
can assign the user's permitted modules/actions; team membership and
ownership constrain the resulting access. This gives the flexibility
needed for someone working across Sales + Accounts, without turning JDK
into a complicated enterprise IAM system.

## Implementation approach

Per [`../ENGINEERING_PRINCIPLES.md`](../ENGINEERING_PRINCIPLES.md) §16
and the roadmap's audit-first rule: see
[`../audit/PERMISSIONS_AUDIT.md`](../audit/PERMISSIONS_AUDIT.md).

**What's implemented:**

- `role_permissions` (organisation, role, module_key, action → scope)
  and `user_permissions` (organisation, user, module_key, action →
  scope) — §4's role default and §5/§6's per-user override, as two small
  tables rather than one polymorphic one (avoids a nullable-column
  partial-unique-index, which MySQL — this project's production target —
  doesn't support portably). `module_key`/`action` are free-form
  strings, not a fixed catalog: §2 says these come from real modules'
  workflows, so a future module registers a new key by writing a
  permission row, not by editing a Python constant (`jdk_clean`'s
  `PAGE_KEYS` tuple required exactly that edit — see
  [`../audit/PERMISSIONS_AUDIT.md`](../audit/PERMISSIONS_AUDIT.md)).
- `get_effective_scope(db, user, module_key, action)` and
  `can(db, user, module_key, action)` (`app/services/authorization_service.py`)
  — the `can(user, action, resource)` concept from §11, minus the
  `resource` argument: no concrete resource type exists yet (Sales,
  Inventory, etc. are Phase 2/3), so this answers "is X allowed, at what
  scope" for a module+action; a future module supplies the resource-level
  ownership/team check itself using that scope, per §7's evaluation
  order.
- `get_user_team_ids(db, user)` — the one shared "which teams can I see"
  building block every future module's `TEAM`-scope query filters
  against, per §12's `WHERE ... team_id IN (...)` pattern.
- Admin-gated management API: `PUT`/`DELETE
  /api/permissions/roles/{role}/{module_key}/{action}`, `GET
  /api/permissions/roles`, `PUT`/`DELETE
  /api/permissions/users/{user_id}/{module_key}/{action}`, `GET
  /api/permissions/users/{user_id}` — all `require_admin`, all re-scoped
  to the admin's own organisation. §9's "Manager cannot grant... Team
  Member cannot manage permissions" holds by construction: neither role
  is in `ADMIN_ROLES`, so both get a flat 403 on every one of these
  endpoints — no special-casing needed.
- `GET /api/permissions/me?module_key=...&action=...` — self-service,
  ungated beyond authentication: a user checking their own effective
  scope isn't a security-sensitive read (Principle 3 — visibility is a
  UI concern), and a future frontend needs this to decide what to show.

**Deliberately not implemented:**

- A generic, resource-agnostic `scope_filter()` query-builder. Writing
  one now, with no concrete table's `team_id`/`owner_id` columns to
  validate it against, would be exactly the abstraction-with-no-caller
  Principle 5 rules out. §12's `WHERE organisation_id = ? AND team_id IN
  (...)` pattern is documented here as the contract; `get_user_team_ids`
  is the one piece of it that's genuinely reusable today, and is
  implemented.
- Enforcement of scope against real records (§13 criteria 5, 6, 11, 12).
  No module has records to scope yet — these are re-verified once Phase
  2/3 modules exist and actually call `can()`/`get_effective_scope()`.
- Any change to `GET /api/users`/`GET /api/teams`'s existing, deliberately
  ungated read access. Those were an explicit simplicity choice made
  before this module existed (see `users.md`/`teams.md`); retrofitting
  them to consult permissions now would be an unrequested behaviour
  change, not something this module's spec asks for.
