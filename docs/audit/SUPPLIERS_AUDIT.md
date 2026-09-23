# Suppliers — Audit of jdk_clean

Audited before building `docs/modules/suppliers.md`, per Principle 5 (reuse
before creating) and Principle 16 (audit before changing). Scope: does
jdk_clean's Supplier implementation contain anything worth reusing, and
what does it get wrong that the new module should avoid repeating? The
user's own framing for this module: "much lighter than Customers because
the expected volume is only about 10" records per organisation.

## 1. Full field list

`backend/app/models/supplier.py` / DDL `backend/schema.sql:252-296` in
jdk_clean. Core operational fields: `code` (unique, auto-generated),
`name`, `contact_person`, `email`, `phone`, `address`, `city`, `country`,
`payment_terms_days`, `status` (active/inactive/suspended).

CRM/workflow bloat, all with no real jdk_erp equivalent to justify porting:
`po_approval_threshold_override` / `discount_approval_threshold_override`
(per-supplier overrides of a global approval rule — no such rule exists in
jdk_erp yet), `mode_of_supply` (direct/distributor/broker/import — unused
downstream per the audit), `rating` (1–5 stars, no scoring engine behind
it), a full `onboarding_status` workflow
(pending → under_review → active/on_hold/rejected) the model's own
docstring admits was "mirrored from Customer's onboarding workflow
exactly," and ID-document upload/verification fields the same docstring
admits nothing currently gates on for suppliers. None of this is ported.

## 2. Supplier↔Material relationship

jdk_clean has a real, well-designed join table: `supplier_materials`
(`backend/app/models/supplier_material.py`, DDL `schema.sql:374-403`),
FK'd to both `suppliers.id` and `raw_materials.id`, carrying
`purchase_price`, `currency`, `lead_time_days`, `moq`,
`max_supply_quantity`, `is_preferred`, and `status`. Purchase orders
reference a real `supplier_id`, never free text. `raw_materials.default_supplier_id`
is a legacy FK the model's own docstring calls "kept only for
compatibility" — `supplier_materials` is the actual source of truth.

**Decision for jdk_erp: do not build this relationship now.** jdk_erp has
no Products/Raw Materials model yet (`docs/ROADMAP.md` lists both as
sibling Phase 2 items, not yet implemented — confirmed via
`ls backend/app/models/`). Building the other half of a join table with
nothing to join to would be pure speculation (Principle 5). When Raw
Materials/Products land, `supplier_materials`' shape (price, MOQ, lead
time, `is_preferred`, `status`) is solid prior art worth reusing as-is;
until then, Procurement (also unbuilt) is free to reference a supplier
directly on a purchase order with no catalog constraint, exactly as
jdk_clean's own `purchase_orders.supplier_id` does.

## 3. Organisation/tenant scoping

jdk_clean has **no organisation-scoping concept at all**, on Supplier or
any other table — a full-backend grep for `organisation_id` /
`organization_id` / `tenant_id` / `company_id` returns zero hits anywhere
in the app. It's a single-tenant deployment; what looked like
per-organisation Customer scoping is actually `assigned_to`-based
ownership scoping for the `team_member` role only
(`docs/audit/CUSTOMERS_AUDIT.md`), unrelated to multi-tenancy.

**Decision for jdk_erp: Supplier is organisation-scoped, same as every
other master built so far.** There is no jdk_clean precedent to follow or
diverge from here — jdk_erp is multi-tenant by its own established
architecture (`OrganisationScopedMixin`, used by Category/Unit/Customer),
and Supplier follows that same convention.

## 4. Uniqueness rules

DB-level: only `code` is unique (auto-generated via a number-series
service, prefix `SUP` — not user-typed). No unique constraint on `name`,
and no tax-ID/GSTIN field exists at all. Application-level: an
`_check_duplicate_phone` scan (`app/crud/master_data.py:253`) normalizes
phone and loops over every non-deleted supplier — the same O(n) defect
already found and fixed in the Customers audit.

**jdk_erp**: `code` auto-generated (unique per organisation, reusing
`app/core/id_formats.py`'s `IdFormat`, prefix `SUP`), `name` unique per
organisation (stricter than jdk_clean — see `app/models/supplier.py`'s
docstring for why), `phone` normalized to digits-only at write time and
enforced unique per organisation at the DB level when provided, fixing the
same O(n) defect the Customers audit already identified and fixed once.

## 5. Contacts/addresses structure

Flat fields only — `contact_person`, `email`, `phone`, `address`, `city`,
`country` directly on the supplier row. No child tables for multiple
contacts or addresses (unlike Customer, which at least has separate
billing/shipping address fields). jdk_erp keeps the same flat shape,
collapsing `city`/`country` into the single `address` free-text field
Category/Unit-tier masters already use elsewhere in this app.

## 6. Lifecycle

`status` enum (active/inactive/suspended) plus soft delete via
`deleted_at`. No delete guard: nothing checks for existing purchase orders
or `supplier_materials` rows before soft-deleting a supplier. Full
onboarding workflow copy-pasted from Customer.

**jdk_erp**: a plain `is_active` boolean, same as Category/Unit/Customer —
no third "suspended" state, no onboarding workflow. No delete guard is
needed either: there's no hard delete, and nothing downstream references
`suppliers` yet (Procurement is unbuilt) — deactivating only affects
whether a supplier can be picked for new records, the same rule already
established for Category/Unit/Customer.

## 7. Frontend

A clean list page (search + status filter, code/name/city-country/terms/
rating/status columns) sits behind a much heavier detail experience: a
6-tab detail page (Overview/Purchasing/Onboarding/Documents/Materials/
History) and a 5-step onboarding wizard. Disproportionate for ~10 records
per organisation. jdk_erp builds a single flat list page with an
inline create/edit form dialog, matching Category/Unit/Customer exactly —
no tabs, no wizard, no detail route.

## 8. Known defects / later removals

Git history is a single squashed commit, so no fine-grained history to
mine. No supplier-specific added-then-reverted feature exists in the
migration set (unlike Units of Measure's conversion-ratio saga). Migrations
are purely additive, each one adopting more of the Customer pattern
(capability fields, onboarding status, auto-code, ID verification, return
dates) — no documented pain points in comments.

## 9. Who can create/edit/deactivate

Generic page-permission matrix: page_key `"suppliers"`, admin bypasses
everything, `viewer` is read-only, every other role is governed by
department-level read/write permission with no supplier-specific gate and
no ownership/assignment scoping (unlike Customer's `team_member` scoping).
Any user whose department has write access on the `suppliers` page can
create/edit/deactivate/onboard any supplier.

**Decision for jdk_erp**: reuse Category/Unit's plain admin-gated shape
(`require_admin` on create/update/status) rather than jdk_clean's
department-permission matrix or Customer's permission-scope engine —
there's no ownership dimension to a vendor list this small, and the
existing admin gate is simpler and sufficient at ~10 records/organisation.
Read stays open to any authenticated organisation member, same reasoning
as Category/Unit/Customer: a supplier is reference data every future
Procurement consumer needs to look up, not a privileged view.

## Bottom line

Supplier ships as the lightest master built so far: flat contact fields,
auto-generated code, name/phone uniqueness per organisation, plain
is_active lifecycle, fully admin-gated mutations, open read — no
onboarding workflow, no rating, no ID verification, no approval-threshold
overrides, and (for now) no supplier↔material relationship, deferred until
Products/Raw Materials exist to be the other half of it.
