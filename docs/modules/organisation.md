# JDK Organisation

The next foundation layer after [`authentication.md`](authentication.md),
per [`../ROADMAP.md`](../ROADMAP.md) Phase 1. Kept deliberately small: a
top-level data and access boundary, not a multi-tenant SaaS platform.

## 1. Purpose

Organisation answers:

> Which business does this user and this data belong to?

Everything inside JDK belongs to an organisation:

```text
Organisation
    ├── Users
    ├── Teams / Departments
    ├── Customers
    ├── Suppliers
    ├── Products
    ├── Inventory
    ├── Sales
    ├── Production
    └── Finance
```

## 2. Organisation record

Kept simple:

- Organisation ID
- Organisation name
- Code/short identifier
- Contact details
- Address
- Currency
- Timezone
- Active/inactive
- Created/updated timestamps

Don't add settings until a real requirement exists.

## 3. Data ownership

Every organisation-owned business record must have a clear organisation
relationship:

```text
organisation
    ↓
customer
    ↓
quotation
    ↓
order
    ↓
production
    ↓
delivery
```

A user from Organisation A must never be able to access Organisation B's
data. Enforced server-side, not through frontend filtering.

## 4. User relationship

A user belongs to an organisation. For the current JDK scope:

**One user → one organisation.**

Don't introduce multi-organisation membership unless the business
actually requires it.

```text
Organisation
    ↓
User
    ↓
Role
    ↓
Team / Department
```

## 5. Organisation + RBAC boundary

Keep responsibilities separate:

| Layer            | Question                                    |
| ----------------- | -------------------------------------------- |
| Organisation      | Which business?                              |
| Authentication     | Who are you?                                 |
| RBAC               | What role do you have?                       |
| Team scope         | Which part of the organisation can you access? |

This prevents the user table or role system becoming overloaded.

## 6. Organisation administration

Super Admin should be able to:

- Create organisation
- Edit organisation details
- Activate/deactivate organisation

Admin operates inside an organisation. An Admin should not be able to
escape their organisation boundary.

## 7. Deactivation

If an organisation becomes inactive:

- Its users cannot log in.
- Its business data remains intact.
- Historical documents remain accessible to authorised system
  administrators.
- Data is never deleted simply because the organisation is inactive.

## 8. Database principle

`organisation_id` should be consistently available on organisation-owned
data. Use foreign keys, indexes, and uniqueness constraints where
appropriate — e.g. a customer identifier might be unique *within* an
organisation, rather than globally.

## 9. Performance

Organisation filtering should be cheap: large transactional tables should
be able to efficiently filter by `organisation_id` + the relevant business
index. Don't build a complex tenant-isolation framework for a small ERP.

## 10. Acceptance tests

Organisation is correct when:

1. A user belongs to exactly one organisation.
2. Every business record belongs to the correct organisation.
3. Organisation A cannot access Organisation B's data.
4. Admin cannot create users outside their organisation.
5. Deactivating an organisation prevents its users from logging in.
6. Existing historical data remains intact.
7. Organisation information is available consistently to the
   application.
8. Queries do not accidentally omit the organisation boundary.
9. Organisation-level access works consistently across every ERP module.

## The structure being built

At this stage:

```text
ORGANISATION
      │
      └── USER
           │
           └── AUTHENTICATION
```

Then Teams/Departments + Roles/RBAC on top:

```text
ORGANISATION
      │
      ├── Teams / Departments
      │       └── Users
      │
      └── Users
              └── Role
```

Not a generic SaaS multi-tenancy framework. The principle for JDK:

> Strong organisation boundary, simple implementation, no unnecessary
> multi-tenant complexity.

## Implementation approach

Per [`../ENGINEERING_PRINCIPLES.md`](../ENGINEERING_PRINCIPLES.md) §16
and the roadmap's audit-first rule: `jdk_clean` was audited first — see
[`../audit/ORGANISATION_AUDIT.md`](../audit/ORGANISATION_AUDIT.md).
It has no organisation concept at all (confirmed single-tenant), so there
is nothing to port forward here; this module is built fresh, directly
against this spec.

Two things this module deliberately does **not** do yet, because they
belong to layers not built yet:

- **No admin API to create/edit/deactivate an organisation.** §6 requires
  a Super Admin role to gate that, and RBAC doesn't exist yet. Building
  an unauthorized write endpoint just to call this "done" would violate
  Principle 3 (server-side authority) — so for now, the only way to
  create an organisation is the `seed_admin` script, and the write API
  is a tracked follow-up once RBAC lands.
- **No cross-module query enforcement.** §3/§8 apply to every future
  organisation-owned table (customers, products, orders, ...), which
  don't exist yet either. What exists now is the *pattern* every one of
  those tables must follow: an `OrganisationScopedMixin` giving a
  required, indexed `organisation_id` foreign key, so there's one
  definition of "how a table belongs to an organisation," not a new one
  invented per module.

What *is* implemented now, because both dependencies already exist:

- The full organisation record (§2).
- `GET /api/organisations/me` — the one place "which organisation am I
  in" is available to the application (§7 acceptance criterion), read
  by any authenticated user for their own organisation only.
- Deactivation blocking login (§7, §10 acceptance criterion 5) — enforced
  in `auth_service.login`, and also in current-user resolution so an
  already-issued token stops working on the next request once the
  organisation goes inactive, not just at the next login.
