# JDK Users

Third foundation layer, after [`authentication.md`](authentication.md) and
[`organisation.md`](organisation.md), per [`../ROADMAP.md`](../ROADMAP.md)
Phase 1. The User record is the central identity — it does not contain
role, permission, or team-hierarchy logic itself.

## 1. Purpose

A User represents a person who operates JDK within an organisation. The
User record is the single source of truth for that person.

```text
Organisation
     ↓
   User
     ├── Authentication
     ├── Role
     └── Team / Department
```

## 2. User record

Kept small:

- User ID
- Organisation ID
- Full name
- Login identifier — email or username
- Password hash
- Active/inactive status
- Role
- Team/department
- Created at
- Updated at
- Last login

Only add profile fields when there is a real ERP requirement.

## 3. User lifecycle

```text
Create
  ↓
Active
  ↓
Inactive
```

Never delete a user who has historical transactions. Deactivate instead,
and retain historical ownership/audit information.

## 4. Creating a user

An authorised administrator should be able to create a user, assign a
role, assign a team, set an initial password / trigger a password reset,
and activate/deactivate. Validation: required fields, login identifier
unique within the organisation, valid role, valid team, password policy,
and a valid organisation relationship.

## 5. Role and team

```text
User
 ├── one Role
 └── one Team / Department
```

No competing roles or nested team memberships unless a genuine
requirement emerges. Role and team determine access later, through RBAC.
**Users themselves do not contain permission logic.**

## 6. Changing users

An authorised administrator can change name/details, change role, move
team, activate/deactivate, and reset password. Changes take effect
immediately for subsequent authorization checks. Changing a user's role
or team must never alter their historical records — e.g. if a salesman
moves from Team A to Team B, old quotations stay associated with the
original user and keep their history.

## 7. Ownership vs access

- **Ownership** answers: who created/owns this record?
- **RBAC/team access** answers: who is allowed to see or modify it?

Never overwrite historical ownership when a user changes teams.

## 8. Security

- Never expose password hashes through normal APIs.
- Never allow a user to modify their own role or organisation.
- Never accept organisation ID blindly from the frontend — the server
  determines it from the authenticated user.
- Server validates role/team changes.
- Inactive users cannot authenticate.

## 9. Performance

Keep the User object lightweight. Don't load all permissions, all
customers, all transactions, or all team members every time the current
user is retrieved — load related data only when required. Index the
fields actually used for login, organisation filtering, active status,
team, and role.

## 10. Acceptance tests

1. Admin creates a user.
2. User belongs to exactly one organisation.
3. User has one primary role.
4. User has one team/department.
5. Duplicate login identifier is rejected.
6. Invalid team/role assignment is rejected.
7. User can be activated/deactivated.
8. Inactive user cannot log in.
9. User can be moved between teams.
10. User can be promoted/demoted through authorised administration.
11. Historical records remain unchanged after role/team changes.
12. User cannot manipulate organisation, role or team through API
    requests.
13. Users from one organisation cannot access users from another
    organisation.

## Foundation so far

```text
ORGANISATION
     │
     └── USERS
          ├── Authentication
          ├── Role
          └── Team / Department
```

Next: Teams/Departments (organisational scope), then Roles & RBAC
(authority) — kept separate, on top of Users, not inside it.

## Implementation approach

Per [`../ENGINEERING_PRINCIPLES.md`](../ENGINEERING_PRINCIPLES.md) §16
and the roadmap's audit-first rule: see
[`../audit/USERS_AUDIT.md`](../audit/USERS_AUDIT.md). The core User
identity (§2, minus role/team) was already built while implementing
authentication, so this phase adds what's genuinely new: an
organisation-scoped user directory and the indexing §9 asks for.

**Deferred to the layers this spec itself says come next**, and why:

- **No `role`/`department` columns yet.** They'd be foreign keys into
  tables (`roles`, `departments`) that don't exist until the Team/RBAC
  phases. A nullable column pointing at nothing isn't a real field —
  it's added in the same migration that creates what it points to.
- **No admin API to create/edit/deactivate/assign-role users.** §4/§6
  require an "authorised administrator," which only RBAC can define.
  Same reasoning as organisation's deferred admin API (see
  [`ORGANISATION_AUDIT.md`](../audit/ORGANISATION_AUDIT.md)) — shipping
  a write endpoint with no real authorization check would violate
  server-side authority (Principle 3) and directly contradicts §5's
  instruction that Users must not contain permission logic: gating it
  with anything short of real RBAC (e.g. an `is_admin` flag on User)
  would be adding exactly the permission logic this module is told not
  to hold. `scripts/seed_admin.py` remains the only way to create a user
  until then; acceptance criteria 1, 3, 4, 6, 9, 10, 11 are consequently
  deferred too.
- **Login identifier uniqueness stays global, not per-organisation.**
  §4 and Organisation §8 both call for uniqueness scoped to the
  organisation. That was deliberately not implemented: today's login
  (`POST /api/auth/login`) takes a bare username with no organisation
  selector, so if two organisations could each have a user named
  `admin`, login couldn't tell them apart. Per
  [`organisation.md`](organisation.md)'s own principle — *"strong
  organisation boundary, simple implementation, no unnecessary
  multi-tenant complexity"* — global uniqueness is kept as the simpler,
  unambiguous choice for a product where one deployment realistically
  serves one active business. This is a deliberate trade-off, not an
  oversight: revisit it (adding an organisation selector to login) only
  if JDK ever needs several organisations sharing one login surface.

**Implemented now**, because both dependencies (Organisation,
Authentication) already exist:

- `GET /api/users` and `GET /api/users/{id}` — an organisation-scoped
  user directory. Any authenticated user can read it (there's no role
  system yet to restrict it further); it's read-only and never exposes
  `password_hash`, so it can't be used to escalate privilege or leak
  another organisation's data (a request for another organisation's user
  ID returns 404, not a 403 that would confirm the ID exists elsewhere).
- A composite `(organisation_id, is_active)` index, replacing the
  single-column `organisation_id` index — the query this module actually
  runs ("active users in my organisation") is a leftmost-prefix match on
  it, so nothing is lost for a plain organisation filter either.
- `UserOut`, the one public-safe representation of a user, now shared
  between `GET /api/auth/me` and the new directory endpoints instead of
  each defining its own shape.
