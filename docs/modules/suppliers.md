# JDK Master Data: Suppliers

Third entity of [`../ROADMAP.md`](../ROADMAP.md) Phase 2 — Master Data,
following Categories and Units of Measure. Suppliers is the vendor master
Procurement will reference once it's built — reference/master data, not a
business transaction. Expected volume is approximately 10 suppliers per
organisation, so this is deliberately the lightest master built so far,
lighter even than Categories/Units of Measure.

## 1. Purpose

Establish the single authoritative supplier record. At ~10 suppliers per
organisation, this is a small, admin-curated vendor list — not a supplier
portal, not a vendor-management/scoring system, not an onboarding
workflow.

## 2. Supplier record

A supplier has: id, code (auto-generated, unique per organisation), name
(required, unique per organisation), contact_person (optional), phone
(optional, normalized to digits-only, unique per organisation when
provided), email (optional), address (optional, single free-text field),
active/inactive state, organisation ownership, created/updated timestamps.
Flat fields only — no separate contacts/addresses child tables (see
[`../audit/SUPPLIERS_AUDIT.md`](../audit/SUPPLIERS_AUDIT.md) #5).

## 3. Supplier usage

```text
Supplier
   │
   └── Purchase Order (not yet built)
```

There is deliberately **no Supplier↔Material relationship yet**.
jdk_clean's real `supplier_materials` join table (price, MOQ, lead time,
preferred flag) is solid prior art worth reusing — but only once
Products/Raw Materials exist in this codebase to be the other half of it
(see audit #2). Until then, a future Procurement module references a
supplier directly on a purchase order, with no catalog constraint,
matching jdk_clean's own `purchase_orders.supplier_id` shape.

## 4. Data ownership and organisation scope

Suppliers are organisation-owned records (`OrganisationScopedMixin`, same
as every other master built so far). The backend determines organisation
from the authenticated user's session context; a client-supplied
`organisation_id` is never trusted. Every supplier query and mutation is
scoped to the caller's own organisation; a supplier id belonging to
another organisation 404s rather than confirming its existence. Note this
decision has no jdk_clean precedent to follow: jdk_clean has no
organisation/tenant-scoping concept anywhere in its codebase (audit #3) —
Supplier simply follows jdk_erp's own established multi-tenant
convention.

## 5. Administration

Reuses the existing Foundation mechanisms directly — no supplier-specific
version of any of these was built:

- List/search/sort/pagination: the same `paginate`/`apply_sort`/
  `apply_keyword_filter`/`PaginatedResponse` contract every master uses.
- Create/edit/status-change: the same `require_admin`-gated,
  `audit_service.log_event`-backed pattern Categories/Units of Measure
  use — **not** Customer's permission-scope engine. Unlike Customer, a
  supplier has no ownership/assignment dimension at all, so the plain
  admin gate is the right shape here, not a scaled-down version of the
  scope engine.
- Frontend: `DataTable`, `FilterBar`, `FormDialog`, `ConfirmDialog`,
  `ActionMenu`, `Badge`, `useServerTable`, `useDebouncedValue` — the same
  common list foundation every master-data page composes.

Read access (`GET /api/suppliers`, `GET /api/suppliers/{id}`) is open to
any authenticated organisation member, same as Categories/Units of
Measure — it's reference data a future Procurement consumer (or anyone
raising a purchase request) needs to look up, not a privileged view. Only
create/edit/activate-deactivate are admin-gated.

`code` is generated server-side (`app/core/id_formats.py`'s
`SUPPLIER_ID`, prefix `4` + a 5-digit per-organisation sequence —
updated from an earlier `SUP` + 4-digit letter-prefixed shape to the
fixed 6-digit, all-numeric, per-organisation-digit-prefixed shape every
Phase 2 master now shares, per explicit user instruction), the same
mechanism Customer uses — never client-supplied.

## 6. Deactivation and referential integrity

```text
Active
  │
  ▼
Inactive
```

No delete endpoint — suppliers are never hard-deleted, matching every
other master. An inactive supplier remains visible (including via
`include_inactive=true`) for historical/reference display, and can be
reactivated by an admin through the same status endpoint. No delete guard
is needed: nothing in jdk_erp references `suppliers` yet (Procurement is
unbuilt), so there's nothing for a soft-deactivate to leave dangling —
deactivation only governs whether the supplier can be *newly selected*,
the same rule already established for Category/Unit/Customer.

## 7. Database integrity

`suppliers` table: primary key, `organisation_id` FK to `organisations`
(`ondelete=RESTRICT`, indexed), `code`/`name` required, unique per
`(organisation_id, code)`, `(organisation_id, name)`, and
`(organisation_id, phone)` when phone is provided. `phone` is normalized
to digits-only at write time (`app/schemas/supplier.py`), so the DB-level
unique constraint alone is sufficient — no O(n) application-level rescan
(the same defect the Customers audit already found and fixed once, and
which jdk_clean's real Supplier implementation repeats independently —
see audit #4).

## 8. Performance

No caching layer, no specialised search infrastructure — the expected
volume (~10 rows per organisation) doesn't justify it, same reasoning as
Categories/Units of Measure. Common list components are still reused for
consistency with every other master, even though pagination will
realistically never engage.

## 9. Integration

No consuming module (Procurement, Purchase Orders) exists yet in this
codebase. This module establishes the authoritative supplier record for
Procurement to reference by foreign key when built, per Principle 5
(reuse before creating) — never a free-text supplier name on a future
purchase order.

## 10. Acceptance criteria

**Audit**: `jdk_clean` audited — a real Supplier implementation exists
there with a working `supplier_materials` join-table pattern worth
reusing later, but also carries an onboarding workflow, rating, and
ID-verification fields copy-pasted from Customer with no real consumer
(see [`../audit/SUPPLIERS_AUDIT.md`](../audit/SUPPLIERS_AUDIT.md));
`jdk_erp` audited — confirmed fully greenfield before implementation.

**Data**: identity defined (id/code/name/contact_person/phone/email/
address/is_active); name required; code/name/phone unique per
organisation; organisation ownership enforced at the DB level;
active/inactive lifecycle defined; no hard delete.

**Access**: existing RBAC (`require_admin`) reused, no new authorization
layer; organisation isolation enforced server-side on every query and
mutation; a non-admin's create/edit/status-change attempt is rejected
with 403; a cross-organisation id 404s on every endpoint including
mutations; read is open to any authenticated organisation member.

**UI**: existing common list/form/modal/filter components reused with no
supplier-specific duplicate; create/edit validation (blank name rejected,
name/phone conflicts surfaced inline); active/inactive state shown via
the shared `Badge`; empty/loading/error states use the shared patterns; a
non-admin sees the same list with no mutating controls.

**Integration**: no parallel supplier implementation exists anywhere in
the codebase (confirmed by audit); the table is ready for Procurement to
reference by foreign key once built; no speculative
Supplier↔Material relationship built ahead of Products/Raw Materials
existing.

**Testing**: create (with auto-generated sequential code), edit,
deactivate, reactivate, duplicate name/phone rejection (409), phone
normalization, invalid/cross-organisation reference (404), permission
enforcement (403 for non-admin mutations, open for reads), audit event
recorded for create/edit/status-change with the correct actor.

## 11. The structure being built

```text
                    ┌─────────────────┐
                    │    Supplier     │
                    │                 │
                    │ ID / Code       │
                    │ Name            │
                    │ Contact info    │
                    │ Status          │
                    │ Organisation    │
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │ Purchase Order  │
                    │  (not yet       │
                    │   built)        │
                    └─────────────────┘
```

## 12. Most important architectural rule

One authoritative Supplier implementation, correctly scoped, correctly
protected, and proportional to a ~10-record vendor list — not a
vendor-management platform. No onboarding workflow, no rating/scoring, no
ID verification, no per-supplier approval overrides, and no speculative
Supplier↔Material relationship until Products/Raw Materials actually
exist to be its other half.

## Implementation approach

Per [`../ENGINEERING_PRINCIPLES.md`](../ENGINEERING_PRINCIPLES.md) §16
("Audit before changing"): see
[`../audit/SUPPLIERS_AUDIT.md`](../audit/SUPPLIERS_AUDIT.md). Structurally
mirrors Category/Unit's admin-gated shape for every mutation (no
permission-scope engine, no ownership dimension), combined with
Customer's flat contact-field shape and auto-generated `code` pattern
(`app/core/id_formats.py`'s `SUPPLIER_ID`, reusing the exact same
generate-with-retry-on-conflict approach `POST /api/customers` already
uses). `MASTER_DATA_MODULE` (the same shared audit-module constant
Categories/Units of Measure/Customers already log under) is reused again
here, not a new `SUPPLIER_MODULE` constant.
