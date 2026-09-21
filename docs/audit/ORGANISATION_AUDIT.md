# Organisation Audit — `jdk_clean`

Phase 0 audit of the organisation/tenancy layer, per
[`../ROADMAP.md`](../ROADMAP.md) and the spec in
[`../modules/organisation.md`](../modules/organisation.md).

## Verdict

**Build fresh — there is nothing to reuse.** `jdk_clean` has no
organisation or tenancy concept anywhere in the codebase.

## Evidence

A case-insensitive search for `organi[sz]ation`/`tenant` across
`backend/` returns five files, and every match is the English word
"organization" used in a comment or UI-section label, not an entity:

- `schema.sql:39` — a comment describing departments as "organizational."
- `app/core/permissions.py:2` — "People & Organization" as the name of a
  settings menu section (which is actually about departments/roles).
- `app/models/user.py:33`, `app/models/department.py:10` — same "People &
  Organization" UI-section reference.
- `app/models/product.py:59` — "organization aid" describing a product
  tagging feature, unrelated to tenancy.

There is no `organisations`/`organizations`/`tenants` table in
`schema.sql`, no `organisation_id`/`tenant_id` column on any table
(confirmed in the authentication audit and re-confirmed here), and no
model, middleware, or query filter anywhere that scopes data by business.
`jdk_clean` is a single-tenant application: one deployment serves exactly
one business, and every table is implicitly "owned" by whoever's running
that deployment.

## What this means for the rebuild

Because there's no existing implementation to audit for duplication,
dead code, or reuse candidates, this module is built directly from the
spec rather than ported forward. The one thing carried over from the
authentication audit is already in place: `users.organisation_id` was
added when the authentication module was built (see
[`AUTHENTICATION_AUDIT.md`](AUTHENTICATION_AUDIT.md) action item 6), so
the one-user-one-organisation relationship the spec requires already
exists at the database level — this module adds the `organisations`
table it points to, plus the fields and enforcement the spec calls for.

## Scope decisions

- No admin API to create/edit/deactivate organisations yet — that
  requires a Super Admin role, which doesn't exist until RBAC is built.
  Tracked as a follow-up in [`../modules/organisation.md`](../modules/organisation.md),
  not built half-authorized just to check a box.
- No other organisation-owned tables exist yet (customers, products,
  etc. are Phase 2 Master Data), so there's nothing else to retrofit an
  `organisation_id` onto right now. What ships instead is the reusable
  pattern (`OrganisationScopedMixin`) every future table uses, so the
  column, its foreign key, and its index are defined once.
