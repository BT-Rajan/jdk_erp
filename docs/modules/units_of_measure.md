# JDK Master Data: Units of Measure

Second entity of [`../ROADMAP.md`](../ROADMAP.md) Phase 2 — Master Data,
built alongside [`categories.md`](categories.md) on the Phase 1
foundation. Establishes the single authoritative definition of units used
for quantities, stock, procurement, BOMs, production and sales where
applicable.

## 1. Purpose

One authoritative unit definition, reused everywhere a quantity is
recorded. Audited against `jdk_clean` first (see
[`../audit/UNITS_OF_MEASURE_AUDIT.md`](../audit/UNITS_OF_MEASURE_AUDIT.md)) —
that codebase's own history (a proper table with conversion → removed →
free text → hardcoded enum) directly answers this module's hardest
question (§5 below) before a line of jdk_erp code was written.

## 2. Unit definition

A unit has: id, name (e.g. "Kilogram"), code (required, e.g. "KG" —
normalized to upper-case), description (optional), active/inactive
state, organisation ownership, timestamps. No hierarchy, no category
(weight/count/volume) field, no conversion column. Kept exactly as
simple as Categories — not a generic measurement framework.

## 3. Unit usage

```text
Unit
 │
 ├── Product        (not yet built)
 ├── Raw Material    (not yet built)
 ├── BOM component quantity   (not yet built)
 ├── Procurement quantity     (not yet built)
 ├── Inventory quantity       (not yet built)
 ├── Production quantity      (not yet built)
 └── Sales quantity           (not yet built)
```

None of these consumers exist yet in this codebase. This module
establishes the authoritative side of the relationship for them to
reference by foreign key when built — the unit defines what a quantity
*means*; it does not own the quantity itself. `Product.unit = Bag`,
`Stock.quantity = 250, Stock.unit = Bag` — the unit stays authoritative,
inventory owns the stock number.

## 4. Unit identity

`code` is required and unique per organisation, normalized to
upper-case at the API boundary — deliberately stricter than Category's
optional code, because a unit's entire reason for existing is its stable
short identifier, and jdk_clean's own free-text period shows exactly
what happens without normalization (`"kg"` growing `"Kg"`/`"KGS"`
siblings with no relationship enforced — see the audit). `name` is
required and unique per organisation. No module maintains its own
separate unit name/symbol — every consumer references this table, never
a locally-typed string.

## 5. Unit conversion

**No conversion mechanism is built.** This is an explicit, evidence-based
decision, not an oversight — see
[`../audit/UNITS_OF_MEASURE_AUDIT.md`](../audit/UNITS_OF_MEASURE_AUDIT.md)
in full. Summary: jdk_clean built exactly this once (a `factor_to_base`
column), and removed it within a week because it conflated a true
physical ratio (`1 ton = 1000 kg`, a universal constant) with a
business-specific packaging assumption (`1 bag = 50 kg`, which the
codebase's own seed-data comment admitted was "a configurable assumption...
edit if wrong for what's actually being bagged") inside one
undifferentiated field. Every downstream consumer that once needed
conversion (BOM explosion) was redesigned instead so a line's unit always
equals its component's own unit — never converts — and that redesign has
held since, at real (if small) data volumes. If a genuine conversion
requirement emerges later (once Products/BOM/Inventory actually exist),
it is a new, deliberate feature built against real evidence at that
time — explicitly not something this module pre-builds speculatively,
per this module's own architectural rule (§14).

## 6. Data ownership and organisation scope

**Organisation-owned** — an explicit decision (see the audit's "Scope
decision" section), since jdk_clean's global unit list reflects that
codebase having no organisation concept at all, not a considered
"units should be global" design. Every other master-data table in
jdk_erp (`Category`, `Team`, `User`) is organisation-scoped via
`OrganisationScopedMixin`; Units of Measure follows the same convention.
The backend derives organisation from the authenticated user's session
context; a client-supplied `organisation_id` is never trusted.

## 7. Administration

Identical mechanisms to Categories, reused directly: `app/core/list_query.py`'s
`paginate`/`apply_sort`, `app/core/search.py`'s `apply_keyword_filter`,
`app/schemas/pagination.py`'s `PaginatedResponse`, `require_admin` for
mutations, `DataTable`/`FilterBar`/`FormDialog`/`ConfirmDialog`/`ActionMenu`/
`Badge`/`useServerTable`/`useDebouncedValue` on the frontend. Read
(`GET /api/units-of-measure`, `GET /api/units-of-measure/{id}`) is open
to any authenticated organisation member; create/edit/activate-deactivate
are admin-gated. No unit-specific version of any common component exists.

## 8. Deactivation and referential integrity

```text
Active
  │
  ▼
Inactive
```

No delete endpoint — units are deactivated, never hard-deleted, same as
every other master record in this codebase. An inactive unit remains
visible (including via `include_inactive=true`, and to a non-admin) for
historical/reference display, and can be reactivated by an admin.
Deactivating a unit never changes the meaning of an existing record that
already references it — once a consuming module exists, changing a
master unit definition must never silently alter a past transaction's
recorded quantity/unit pairing (this module records the rule; enforcing
it against real transactional data is that future module's job).

## 9. Database integrity

`units_of_measure` table: primary key, `organisation_id` FK to
`organisations` (`ondelete=RESTRICT`, indexed), `name` and `code`
required, unique per `(organisation_id, name)` and `(organisation_id, code)`.
No uncontrolled unit strings anywhere in this codebase — the one table
this module adds is the only place a unit is ever defined.

## 10. Performance

No caching layer, no conversion service, no query abstraction beyond
what Foundation already provides — the expected volume (a handful of
rows per organisation) doesn't justify it. The real requirement: this
module must not become the place a future Products/BOM/Inventory module
invents its own, second unit list or a per-module ad hoc conversion.

## 11. Integration

No consuming master exists yet in this codebase. This module establishes
the authoritative side of the relationship for Products, Raw Materials,
BOM, Inventory and Production to reference by foreign key when built —
never a hardcoded list, a parallel enum, or a frontend-only unit
definition.

## 12. Acceptance criteria

**Audit**: `jdk_clean` audited in full, including its unit-conversion
history (see the audit doc); `jdk_erp` confirmed greenfield before
implementation; conversion requirements explicitly evaluated and
rejected with evidence, not assumed away.

**Data**: identity defined (id/name/code/description/is_active); name
and code required; both unique per organisation; code normalized to
upper-case; organisation scope explicitly decided (org-owned, not
global) and enforced at the DB level; active/inactive lifecycle defined;
no hard delete.

**Conversion**: no conversion engine built; the decision is documented
with evidence, not silently skipped; business-specific packaging
relationships and universal physical conversions are explicitly named as
different kinds of things (jdk_clean's own failure), even though neither
is implemented here.

**Access**: `require_admin` reused for mutations, no new authorization
layer; organisation isolation enforced server-side on every query and
mutation; non-admin mutation attempts rejected with 403; cross-organisation
ids 404 on every endpoint including mutations.

**UI**: existing common list/form/modal/filter components reused with no
unit-specific duplicate; create/edit validation (blank name/code
rejected, name/code conflicts surfaced inline, code normalized visibly);
active/inactive state shown via the shared `Badge`; a non-admin sees the
same list with no mutating controls.

**Integration**: no parallel unit implementation exists anywhere in the
codebase; the table is ready for Products/Raw Materials/BOM to reference
by foreign key once built.

**Testing**: create, edit, deactivate, reactivate, duplicate name/code
rejection (409, including a case-insensitive code collision), invalid/
cross-organisation reference (404), permission enforcement (403 for
non-admin mutations, open for reads), audit event recorded for every
mutation with the correct actor, code normalization on both create and
edit.

## 13. Most important architectural rule

One quantity has one authoritative unit meaning throughout JDK. The Unit
master defines the unit; the consuming module owns the quantity and the
business transaction. No module maintains its own unit list, and no
conversion mechanism exists without real evidence that one is needed —
jdk_clean already tried and removed the alternative.

## Implementation approach

Per [`../ENGINEERING_PRINCIPLES.md`](../ENGINEERING_PRINCIPLES.md) §16
("Audit before changing"): see
[`../audit/UNITS_OF_MEASURE_AUDIT.md`](../audit/UNITS_OF_MEASURE_AUDIT.md).
Structurally identical to `Category` (`docs/modules/categories.md`) —
same `OrganisationScopedMixin`/`TimestampMixin` base, same admin-gated
`POST`/`PATCH .../{id}`/`PATCH .../{id}/status` API, same
`MASTER_DATA_MODULE` audit constant. The one deliberate difference from
Category: `code` is required (Category's is optional), and normalized to
upper-case on every write — both directly informed by the audit's
`"kg"`/`"Kg"`/`"KGS"` finding rather than mirrored by default.
