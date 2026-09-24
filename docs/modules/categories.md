# JDK Master Data: Categories

First entity of [`../ROADMAP.md`](../ROADMAP.md) Phase 2 — Master Data,
built on top of the Phase 1 foundation (Organisation, Authentication,
Users, Teams, RBAC, Audit, common list/table/form/modal/filter UI).
Categories is the single authoritative classification structure used to
group master records such as Products and Raw Materials — reference/master
data, not a business transaction.

## 1. Purpose

Establish the single authoritative category structure used to classify
applicable master records. Kept small and simple: the expected category
volume for JDK's current business is approximately 2–3 categories. Not a
generic classification engine.

## 2. Category record

A category has: id, name, code, description (optional), active/inactive
state, organisation ownership, created/updated timestamps. No hierarchy —
nothing in the legacy audit or JDK's current scale justifies a
parent/child tree (see
[`../audit/CATEGORIES_AUDIT.md`](../audit/CATEGORIES_AUDIT.md)).

**Updated by explicit user instruction**: `code` is now required and
system-generated, not the optional/caller-editable field originally
described here — see §4a below. This is a deliberate, later reversal of
this section's own original decision, not a silent one.

## 4a. Code generation

Every Phase 2 master's own identifying code is a fixed 6-digit,
all-numeric, system-assigned value, never caller-supplied or editable
(per explicit user instruction) — `app/core/id_formats.CATEGORY_CODE`
generates Category's own: prefix `5` + a 5-digit per-organisation
sequence (e.g. `500001`, `500002`, ...), assigned the same way
Customer/Supplier's own codes already were (existing count + 1, retried
against a collision under `IntegrityError`) — see
[`boms.md`](boms.md)'s sibling modules for the full per-entity prefix
table (Raw Material `1`, Product `2`, Customer `3`, Supplier `4`,
Category `5`; Production Line/Machine/Warehouse share a `0000`-prefixed
shape instead, capped at 9 records each). Never a hierarchy-encoding or
otherwise meaningful code — purely a stable, unique reference id.

## 3. Category usage

```text
Category
   │
   ├── Product
   │
   └── Raw Material
```

Category logic stays separate from the modules that consume it: Category
defines classification, Product defines the product, Raw Material defines
the material. Neither Product nor Raw Material exists yet in this
codebase — this module establishes the authoritative classification
master those future modules will reference by foreign key, not by
free-text string (the exact anti-pattern `jdk_clean` fell into — see the
audit).

## 4. Data ownership and organisation scope

Categories are organisation-owned records (`OrganisationScopedMixin`,
same as every other business table in this codebase). The backend
determines organisation from the authenticated user's session context; a
client-supplied `organisation_id` is never trusted. Every category query
and mutation is scoped to the caller's own organisation; a category id
belonging to another organisation 404s rather than confirming its
existence (same pattern as Teams/Users/Organisation).

## 5. Administration

Reuses the existing Foundation mechanisms directly — no category-specific
version of any of these was built:

- List/search/sort/pagination: `app/core/list_query.py`'s
  `paginate`/`apply_sort`, `app/core/search.py`'s `apply_keyword_filter`,
  `app/schemas/pagination.py`'s `PaginatedResponse` — identical shape to
  `GET /api/teams`/`GET /api/users`.
- Create/edit/status-change: the same `require_admin`-gated,
  `audit_service.log_event`-backed pattern `PATCH /api/organisations/me`
  and `PATCH /api/organisations/me/status` already established.
- Frontend: `DataTable`, `FilterBar`, `FormDialog`, `ConfirmDialog`,
  `ActionMenu`, `Badge`, `useServerTable`, `useDebouncedValue` — the same
  common list foundation `UsersPage` composes.

Read access (`GET /api/categories`, `GET /api/categories/{id}`) is open
to any authenticated organisation member, same as Teams and Users — it's
read-only reference data every future module needs to look up, not a
privileged view. Only create/edit/activate-deactivate are admin-gated,
via the existing `require_admin` dependency — no new authorization
infrastructure.

## 6. Deactivation and referential integrity

```text
Active
  │
  ▼
Inactive
```

No delete endpoint exists — categories are never hard-deleted, matching
every other master record in this codebase (Users, Teams, Organisation).
An inactive category remains visible (including to a non-admin, and via
`include_inactive=true` on the list endpoint) for historical/reference
display, and can be reactivated by an admin through the same status
endpoint. Products/Raw Materials referencing a category by foreign key
(once those modules exist) are unaffected by their category being
deactivated — deactivation only governs whether the category can be
*newly selected*, a rule those consuming modules enforce themselves when
built, not something Category pre-empts.

## 7. Database integrity

`categories` table: primary key, `organisation_id` FK to `organisations`
(`ondelete=RESTRICT`, indexed), `name` required, unique per
`(organisation_id, name)` and `(organisation_id, code)` — exactly Team's
constraint shape. No generic metadata table, no uncontrolled free-text
category strings anywhere — consuming modules reference `Category` by
foreign key, never by storing a copy of its name.

## 8. Performance

No caching layer, no specialised search infrastructure, no query
abstraction beyond what Foundation already provides — the expected volume
(a handful of rows per organisation) doesn't justify it. The only real
requirement: this module must not become the place a future Products or
Raw Materials module invents its own, second category mechanism.

## 9. Integration

At implementation time, no consuming master (Products, Raw Materials)
exists yet in this codebase — this module establishes the authoritative
side of the relationship for those modules to reference by foreign key
when built, per Principle 5 (reuse before creating): a future Products
module adds a `category_id` FK to this table, never a parallel category
list, hardcoded constant, or frontend-only category definition.

## 10. Acceptance criteria

**Audit**: `jdk_clean` audited — no category mechanism exists there, only
an unvalidated free-text field duplicated across three tables with no
dedup (see [`../audit/CATEGORIES_AUDIT.md`](../audit/CATEGORIES_AUDIT.md));
`jdk_erp` audited — confirmed fully greenfield before implementation.

**Data**: identity defined (id/name/code/description/is_active); name
required; name and code unique per organisation; organisation ownership
enforced at the DB level; active/inactive lifecycle defined; no hard
delete.

**Access**: existing RBAC (`require_admin`) reused, no new authorization
layer; organisation isolation enforced server-side on every query and
mutation; a non-admin's create/edit/status-change attempt is rejected
with 403; a cross-organisation id 404s on every endpoint including
mutations.

**UI**: existing common list/form/modal/filter components reused with no
category-specific duplicate; create/edit validation (blank name
rejected, name/code conflicts surfaced inline); active/inactive state
shown via the shared `Badge`; empty/loading/error states use the shared
patterns; a non-admin sees the same list with no mutating controls.

**Integration**: no parallel category implementation exists anywhere in
the codebase (confirmed by audit); the table is ready for Products/Raw
Materials to reference by foreign key once built.

**Testing**: create, edit, deactivate, reactivate, duplicate name/code
rejection (409), invalid/cross-organisation reference (404), permission
enforcement (403 for non-admin mutations, open for reads), audit event
recorded for create/edit/status-change with the correct actor.

## 11. The structure being built

```text
                    ┌─────────────────┐
                    │    Category     │
                    │                 │
                    │ ID              │
                    │ Name / Code     │
                    │ Status          │
                    │ Organisation    │
                    └────────┬────────┘
                             │
                ┌────────────┴────────────┐
                │                         │
                ▼                         ▼
          ┌───────────┐             ┌──────────────┐
          │  Product  │             │ Raw Material │
          │ (not yet  │             │  (not yet    │
          │  built)   │             │   built)     │
          └───────────┘             └──────────────┘
```

## 12. Most important architectural rule

One authoritative Category implementation, correctly scoped, correctly
protected, correctly referenced, and simple enough to remain reliable.
Not a generic ERP classification engine.

## Implementation approach

Per [`../ENGINEERING_PRINCIPLES.md`](../ENGINEERING_PRINCIPLES.md) §16
("Audit before changing") and the roadmap's audit-first rule: see
[`../audit/CATEGORIES_AUDIT.md`](../audit/CATEGORIES_AUDIT.md). Built
fresh against this spec — `jdk_clean` has nothing to port forward.
Structurally mirrors `Team` (`docs/modules/teams.md`): same
`OrganisationScopedMixin`/`TimestampMixin` base, same
name/code/description/is_active shape, same per-organisation unique
constraints on name and code. Unlike Team (whose own create/edit API was
deferred to a later phase, since RBAC didn't exist yet when it was
built), Category gets a full `POST`/`PATCH .../{id}`/`PATCH .../{id}/status`
API immediately — RBAC already exists, so there is no reason to defer
admin management the way Organisation's and Teams' first passes had to.

`MASTER_DATA_MODULE` is a new, shared audit-module constant (rather than
a `CATEGORY_MODULE` constant scoped to this one entity) — every future
Phase 2 master-data entity (Units of Measure next, then Products, Raw
Materials, ...) logs under the same module name, per Principle 2 (one
source of truth) rather than growing a new module constant per entity.

## Revision 2 — category type

- Every category has a **Type**: `product` or `raw_material`
  (`categories.applies_to`, required). Products only take product
  categories, Raw Materials only raw-material categories (422 otherwise,
  `app/services/category_service.py`); each form's dropdown lists only
  its own type. `GET /api/categories?applies_to=` filters.
- The type can't change while any product or raw material uses the
  category (400).
- A product / raw material keeps a category that has since been
  deactivated: editing it re-sends the unchanged category and saves;
  only choosing a *different* category must be active. The dropdown
  still shows the current (inactive) one.
- The Products and Raw Materials lists load category names for every
  user, not only admins (the Category column was blank for non-admins).
- Migration `0037_category_applies_to.py` backfills: used only by raw
  materials → `raw_material`, otherwise `product`; a category used by
  both stays `product` and gets a "<name> (Raw Material)" copy that its
  raw materials move to.
