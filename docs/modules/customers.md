# JDK Master Data: Customers

Third entity of [`../ROADMAP.md`](../ROADMAP.md) Phase 2 — Master Data,
and the first high-volume operational master with a real
ownership/visibility model, unlike [`categories.md`](categories.md)/
[`units_of_measure.md`](units_of_measure.md). Audited against `jdk_clean`
first — see [`../audit/CUSTOMERS_AUDIT.md`](../audit/CUSTOMERS_AUDIT.md)
in full; this doc assumes that audit's findings throughout.

## 1. Purpose

The single authoritative customer record consumed by Sales:
`Customer → Feasibility → Quotation → Order → Invoice/Payment → Delivery`.
None of those downstream modules exist in jdk_erp yet — this module
establishes the authoritative side of that relationship for them to
reference by foreign key when built.

## 2. Customer definition

Deliberately minimal, per the audit's field-by-field justification:
`code` (auto-generated, unique per organisation), `name` (required, not
deduplicated — see §6), `contact_person`, `phone` (normalized,
duplicate-checked), `email`, `address` (a single field, not a
billing/shipping pair), `assigned_to_user_id` (nullable), `is_active`,
organisation, timestamps. No credit terms, no GL/bank-account fields, no
follow-up/dunning, no ID verification, no onboarding-approval workflow,
no tags/avatar/parent-company linking — every one of those has no
consuming module in jdk_erp yet, and most were flagged by jdk_clean's
own code comments as speculative even there.

## 3. Customer ownership

```text
Organisation
     │
     ├── Sales Manager (role=manager, member of Team X)
     │       │
     │       ├── Salesman A (role=team_member, member of Team X)
     │       │       └── Assigned Customers
     │       │
     │       └── Salesman B (role=team_member, member of Team X)
     │               └── Assigned Customers
     │
     └── Other authorised users (admin/super_admin)
```

One ownership pointer per customer: `assigned_to_user_id`, nullable (an
unassigned customer is valid). No `created_by` column — the audit trail's
`customer_created` event already records who created a customer, the
same way it does for every other master in this codebase. The backend
always derives organisation and, for a `team_member`, the assignee, from
the authenticated session — never from the request body.

## 4. Customer visibility

Resolved per caller, via the already-built permission-scope engine
(`docs/modules/permissions.md`), not new authorization infrastructure:

- **`admin`/`super_admin`**: see every customer in the organisation
  (`ALL`), unconditionally — the same bypass every other admin-gated
  action in this codebase already uses.
- **`manager`**: sees customers assigned to any user who shares a team
  with them (`TEAM`) — resolved via the existing
  `get_user_team_ids()`/`user_teams` join, not a reporting-line
  hierarchy (jdk_erp has no `manager_id` column and, per the Teams
  audit, deliberately never will). A manager on no team sees only their
  own assigned customers.
- **`team_member`**: sees only customers assigned to themselves (`OWN`).

These are the documented defaults from `permissions.md` §4, applied only
when no explicit `role_permissions`/`user_permissions` row exists for
`module_key="customers"`, `action="view"` — an admin can override any
role's or individual user's scope at any time via the existing
`PUT /api/permissions/roles/{role}/customers/view` /
`PUT /api/permissions/users/{user_id}/customers/view` endpoints, and
that explicit grant always wins. Enforced server-side in every list/get
query (`app/services/customer_scope.py`); a customer that exists but is
outside the caller's scope returns 404, not 403, from
`GET /api/customers/{id}` — the same "never confirm existence" reasoning
already used for a cross-organisation id, adopted directly from
jdk_clean's own real, deliberate choice here.

## 5. Customer creation

Open to any authenticated organisation member — onboarding a new
customer is ordinary sales work, not a master-data administration
action (mirrors jdk_clean's own real behaviour: creation stays open to
page-level write access; only editing an *existing* record is
admin-only, see §7). A `team_member`'s new customer is always
auto-assigned to themselves, silently overriding any client-supplied
`assigned_to_user_id` — they can create their own customers but can
never assign one to someone else. An `admin` may specify any active
user in their own organisation, or leave it unassigned; a `manager` may
assign it to themselves, leave it unassigned, or assign it to a member
of a team they head (Sales S2 — see §10). No
approval workflow — a customer is immediately usable once created (see
the audit for why jdk_clean's onboarding-approval workflow isn't ported).

## 6. Duplicate and uniqueness control

- `code`: DB-unique per organisation, server-generated
  (`app/core/id_formats.py`'s `CUSTOMER_ID`, prefix `3` + a 5-digit
  per-organisation sequence — updated from an earlier `CUS` + 4-digit
  letter-prefixed shape to the fixed 6-digit, all-numeric,
  per-organisation-digit-prefixed shape every Phase 2 master now shares,
  per explicit user instruction), never client-supplied.
- `phone`: DB-unique per organisation when provided, normalized to
  digits-only at write time (fixing jdk_clean's O(n) re-scan-on-every-write
  defect — see the audit).
- `name`: **not** unique, deliberately — unlike Category/Team (internal
  classification labels), a customer name is externally-given
  real-world business data; two unrelated real businesses can
  legitimately share a name, and jdk_clean never deduped it either.

## 7. Customer contacts and addresses

Single embedded columns on the customer row (`contact_person`, `phone`,
`email`, `address`) — no child tables, no billing/shipping distinction,
no primary-contact flag. jdk_clean itself never built a proper
one-to-many contacts/addresses system either (see the audit); this
mirrors its actual working shape rather than its `parent_company_id`
workaround for filing individual contacts as separate customer rows.

## 8. Customer lifecycle

```text
Active
   │
   ▼
Inactive
```

No delete endpoint — customers are deactivated, never hard-deleted,
same as every other master in this codebase. An inactive customer
remains visible (via `include_inactive=true`, subject to the same view
scope) for historical/reference display, and can be reactivated by an
admin. Deactivation/reactivation are admin-only (§9) — mirroring
jdk_clean's own real, deliberately strict choice that even a manager
cannot alter an existing customer record's status.

## 9. Customer transaction boundary

Customer Master owns identity, contact/address information, ownership/
assignment, and lifecycle. It does not own feasibility, quotations,
orders, invoices, payments, deliveries, or customer balances — those
belong to their respective (not-yet-built) business modules, which
reference the authoritative customer by foreign key, never by copying
its fields into their own tables (per jdk_clean's own real practice —
see the audit's "Downstream references" section).

## 10. Administration

Reuses the existing Foundation mechanisms directly: `app/core/list_query.py`'s
`paginate`/`apply_sort`, `app/core/search.py`'s `apply_keyword_filter`
(searching name/code/contact_person/phone), `app/schemas/pagination.py`'s
`PaginatedResponse`, and the common `DataTable`/`FilterBar`/`FormDialog`/
`ConfirmDialog`/`ActionMenu`/`Badge`/`useServerTable`/`useDebouncedValue`
on the frontend — the same composition `CategoriesPage`/
`UnitsOfMeasurePage` already use. **Edit and status-change are
admin-gated** (`require_admin`, no new authorization layer);
**reassignment is Department Head only** (Sales S2,
`customer_scope.can_reassign_customer`): `admin`/`super_admin` anywhere
in the organisation; a `manager` only within a team they head — one team
must contain the manager, the current owner and the new owner (so a
manager cannot touch an unassigned customer or un-assign one). It
changes only `assigned_to_user_id`; creation and earlier audit events
are never rewritten; **create and view** are open to
every authenticated organisation member, with view further narrowed by
the caller's resolved scope.

**Sales records** (quotations, orders, ... once built) have no ownership
of their own: Sales record → Customer → `assigned_to_user_id` → the
caller's scope per §4. Every Sales endpoint reuses
`customer_scope.get_accessible_customer` (object-level: 404 when out of
scope, including a `customer_id` named in a create/update body) and
`customer_scope.scope_by_customer` (list/lookup queries) — no separate
Sales permission key or ownership column.

## 11. Customer list UX

Columns: Code, Customer (name), Contact, Assigned To (resolved to a
name via the existing organisation-wide `GET /api/users`, the same
open-read endpoint `UsersPage`/other pages already rely on — no new
endpoint), Status, Actions. No salesman filter control exists — per
jdk_clean's own explicit UI comment adopted here too: a `team_member`
only ever sees their own customers, so a salesman filter would be
meaningless for them; a manager/admin already sees their full permitted
set without needing one at this data volume (a few hundred rows,
already server-paginated).

## 12. Database integrity

`customers` table: primary key, `organisation_id` FK (`ondelete=RESTRICT`,
indexed), `assigned_to_user_id` FK to `users.id` (`ondelete=SET NULL`,
indexed — the hot query this module actually runs, "this salesman's/
team's customers"), `name` required, unique per `(organisation_id, code)`
and `(organisation_id, phone)`. No uncontrolled customer name/contact
strings anywhere else in the codebase — there is nothing else to
reference a customer today, and future Sales modules will reference this
table by foreign key, never a copy.

## 13. Access and security

Every endpoint requires authentication; organisation isolation is
enforced on every query (never a client-supplied `organisation_id`);
view-scope is resolved server-side per §4; mutation authorization is
enforced server-side per §10. Tested for both allowed and deliberately
unauthorized access in every direction: a `team_member` cannot edit,
deactivate, or reassign (403); a `manager` cannot edit or deactivate and
can reassign only within a team they head (403 otherwise); cross-organisation ids 404 on every endpoint including
mutations; a customer outside view scope 404s rather than 403ing.

## 14. Performance

No caching, no search engine, no background indexing — the existing
database/query patterns from Foundation are sufficient at the expected
scale (several hundred customers per organisation). The `assigned_to_user_id`
index is the one genuinely load-bearing addition, supporting both the
`OWN` filter and the `TEAM` filter's subquery.

## 15. Integration

No consuming Sales module exists in jdk_erp yet. This module establishes
the authoritative customer reference — Feasibility, Quotation, Order,
Invoice, and Delivery will each add a `customer_id` foreign key when
built, never a parallel customer table, a hardcoded list, or a
field-level snapshot presented as if it were the master (a transaction
document may legitimately snapshot customer details for legal/historical
reasons when a real business need for that arises — jdk_clean's own
practice was actually the opposite, always live-joining — but that
decision belongs to the module that needs it, not this one).

## 16. Acceptance criteria

**Audit**: `jdk_clean` audited in full — ownership model, visibility
enforcement (the real `_scope_query`/`sales_scope.py` mechanism, not
just field names), duplicate/uniqueness rules, contacts/addresses,
lifecycle, and known defects all traced with file:line evidence (see
the audit doc). `jdk_erp`'s existing permission-scope engine
(`role_permissions`/`user_permissions`/`get_effective_scope`/
`get_user_team_ids`) audited and confirmed as real, working, reusable
code — not vaporware — before writing any Customer-specific logic.

**Data**: stable identity (auto-generated `code`); `name` required;
`code`/`phone` unique per organisation, `name` deliberately not;
organisation ownership enforced at the DB level; `assigned_to_user_id`
ownership/assignment enforced; active/inactive lifecycle defined; no
hard delete.

**Access**: salesman (`OWN`), manager (`TEAM`, via shared team
membership), and admin (`ALL`) visibility all enforced server-side and
tested in both directions (correctly visible, correctly excluded);
cross-organisation access rejected (404) on every endpoint; direct API
access without the UI enforces the identical rules (there is no
UI-only restriction anywhere in this module).

**UI**: common `DataTable`/`FilterBar`/sorting/pagination/`ActionMenu`/
form-validation components reused with no Customer-specific duplicate;
search performs correctly via the standard list contract; mutating
actions (Edit, Assign, Deactivate) are conditionally rendered per role
but never the enforcement itself.

**Integration**: no parallel customer implementation exists anywhere in
the codebase (confirmed by audit); the table and its `assigned_to_user_id`
foreign key are ready for Feasibility/Quotation/Order/Invoice/Delivery
to reference when built.

**Testing**: create (any role, auto-assignment for team_member,
explicit assignment for manager/admin), edit (admin-only), search, sort,
pagination, reassign (admin/manager only, rejects a cross-organisation
assignee), deactivate/reactivate (admin-only), duplicate phone/code
handling, salesman access boundary (own only), manager access boundary
(team only, correctly excluding a salesman not on their team), admin
access (all), cross-organisation isolation, explicit permission-table
overrides of the default scope (proving real reuse of the existing
engine, not a hardcoded rule).

## 17. Most important architectural rule

Customer is a master record, not a sales transaction. There is exactly
one authoritative Customer implementation. Sales modules will consume
it; they will not recreate it. Ownership and visibility are enforced by
the backend (reusing the permission-scope engine `permissions.md`
already built), while common Foundation components provide the UI. Built
for the actual JDK business — several hundred customers, controlled
salesman ownership, manager visibility, strong access control — without
becoming a CRM system.
