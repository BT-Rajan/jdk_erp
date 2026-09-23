# JDK Master Data: Products

Fifth entity of [`../ROADMAP.md`](../ROADMAP.md) Phase 2 — Master Data,
following Categories, Units of Measure, Customers, and Suppliers. Product
is the authoritative definition of what JDK manufactures and sells.
JDK currently has ~20 products, so this stays a simple, admin-curated
master — not a generic ERP/PIM product-engineering framework.

## 1. Purpose

Implement Product as the single authoritative source of what JDK sells
and, where applicable, manufactures. Every downstream consumer
(Feasibility, Quotation, Order, BOM, Production, Inventory, Delivery)
will reference this master by foreign key once built, rather than
maintaining its own product table or free-text product name.

## 2. Product record

A product has: id, code (required, manually entered, immutable after
creation), name (required), category (required FK to the authoritative
Category master), unit of measure (required FK to the authoritative
UnitOfMeasure master), description (optional), default selling price
(required, current/default reference only), manufacturing lead time in
days (optional), customer lead time in days (optional), active/inactive
state, organisation ownership, created/updated timestamps.

Deliberately excluded, all confirmed against
[`../audit/PRODUCTS_AUDIT.md`](../audit/PRODUCTS_AUDIT.md): barcode
(unused anywhere in jdk_clean), weight (unused, no Delivery consumer
yet), reference cost (no cost field exists in jdk_clean at all — no
business rule to preserve), product type (a real distinction in
jdk_clean, but its only consumer is BOM's component polymorphism, and
BOM doesn't exist yet — deferred, not invented ahead of a real consumer),
and the generic `tags`/`properties` JSON fields jdk_clean's own comments
call "not read by any business logic."

## 3. Product classification

**Category**: Product requires an active Category in the caller's own
organisation, validated server-side on every create/update — never a
free-text category string. This is the first real consumer of the
Category master by foreign key, giving concrete meaning to
[`categories.md`](categories.md) #6's "deactivation only governs new
selection" rule for the first time.

**Unit of Measure**: same shape — Product requires an active
UnitOfMeasure in the caller's own organisation. jdk_clean itself briefly
built a real units-of-measure master, then reverted to a free-text enum a
week later (see the audit #3) — that reversal is not followed here;
jdk_erp's own UnitOfMeasure master already exists and is the correct
thing to reference.

**Product code**: one authoritative value, manually entered and
immutable after creation — matching jdk_clean's own real, established
behaviour exactly (see audit #2). Unlike Customer/Supplier, this is *not*
auto-generated; the spec's own instruction not to silently change
established business behavior applies directly here.

## 4. Sales and Customer Lead Time

`customer_lead_time_days` is real operational business data: the time
Sales uses as a reference when committing a delivery date to a customer,
not a description of how long production takes. jdk_clean has no such
field or delivery-calculation engine at all (audit #4) — Sales there
negotiates `Order.requested_delivery_date` entirely by hand, with an
explicit, reasoned override path for changes after confirmation. This
field is therefore designed fresh, directly from that gap, as a simple
reference number of days — never a live calculation engine.

**Historical integrity (binding on every future consumer)**: once a
Quotation/Order module exists and records a customer delivery
commitment, that transaction must store its own committed date/lead-time
value on its own row — never a live re-read of `Product.customer_lead_time_days`.
A later change to a Product's Customer Lead Time must never silently
rewrite a historical quotation or order, the same discipline jdk_clean
itself correctly applies to price (see #6).

## 5. Manufacturing Lead Time

`manufacturing_lead_time_days` represents the expected time to
manufacture the product — a reference value for a future
Feasibility/Planning workflow, never a replacement for an actual
production schedule:

```text
Product
    └── Manufacturing Lead Time
              ↓
       Feasibility / Planning
              ↓
       Actual Production Schedule
```

jdk_clean has no literal lead-time field either, but does have a real,
live capacity-scheduling engine (rate-based: hours/unit, machine/worker
availability, a `production_schedules` table) consumed only by its
Feasibility module, never by Order's delivery-date logic directly (audit
#5) — confirming the two concepts are already architecturally separate
in practice, even without a literal "lead time" field. Building that full
scheduling engine now would be far out of scope for a ~20-product master;
`manufacturing_lead_time_days` is the simple reference value this
module's own diagram calls for, left for a future Feasibility module to
consume (and, if the business needs jdk_clean's richer rate-based
scheduling, to build against its own audit — not this one's).

**Relationship with Customer Lead Time**: deliberately distinct fields
with distinct meanings — Manufacturing Lead Time estimates production
time; Customer Lead Time is what Sales commits to a customer. A future
Feasibility workflow may consult both, together with stock, material,
and machine/resource availability, exactly as jdk_clean's own real
capacity engine does — but building that combination logic is that
future module's job, not this one's.

## 6. Commercial definition

`selling_price` is the current/default reference price only:

```text
Product
    └── Default Selling Price

Quotation (not yet built)
    └── Actual quoted price

Order (not yet built)
    └── Confirmed transaction price
```

Changing a Product's selling price must never alter an existing
quotation or order — confirmed as jdk_clean's own actual (correct)
behaviour: `OrderDetail`/`QuotationDetail` snapshot their own price
columns rather than reading Product live (audit #6). This module has no
transaction table yet to test that discipline against, so
`test_changing_selling_price_does_not_retroactively_change_prior_reads`
(`tests/test_products.py`) instead pins down that `GET /api/products/{id}`
always reflects Product's current value — documenting, for whichever
Quotation/Order module is built next, that it must snapshot price itself
rather than relying on this endpoint for historical accuracy.

No reference-cost field is built — jdk_clean has no cost field on
Product at all (audit #7), so there is no existing business rule to
preserve; add one later only if a real costing/margin workflow proves it
necessary.

## 7. Production relationship

No BOM relationship is built yet — BOM doesn't exist in this codebase.
jdk_clean's own BOM pattern (`boms.product_id` a unique FK, BOM
composition never duplicated onto Product) is documented in the audit
(#8) as the template to follow when BOM is built. Product establishes
only the authoritative product side of that future relationship.

## 8. Inventory boundary

Product carries no stock-quantity fields of any kind — no on-hand,
available, reserved quantity, or stock value. jdk_clean keeps this
separation cleanly (a dedicated `finished_goods_inventory` table,
audit #9) and even its replenishment-threshold pair
(`reorder_point`/`maximum_stock`) is deliberately not ported here: the
user's own field list for this module doesn't call for it, and Inventory
doesn't exist in jdk_erp yet to consume it. Add it, if ever needed, when
that module is built.

## 9. Lifecycle

```text
Active
  │
  ▼
Inactive
```

No delete endpoint — products are never hard-deleted, matching every
other master. No delete guard is needed yet either: nothing in jdk_erp
references `products` (BOM/Quotation/Order/Production/Inventory are all
unbuilt) — unlike jdk_clean, which has real consumers but, per the audit
(#11), *still* has no delete guard protecting a referenced Product, a gap
explicitly not repeated: whichever module becomes the first real
consumer here is responsible for respecting `is_active` at selection
time, the same rule already established for Category/Unit/Customer/
Supplier.

## 10. Organisation scope

Products are organisation-owned records (`OrganisationScopedMixin`, same
as every other master). The backend determines organisation from the
authenticated user's session context; a client-supplied `organisation_id`
is never trusted. jdk_clean has no organisation/tenant-scoping concept
anywhere (audit #12) — there is no precedent to follow here, only
jdk_erp's own established convention to apply, same as Suppliers.

## 11. Administration UX

Reuses the existing common list/form/modal components exactly —
`DataTable`, `FilterBar`, `FormDialog`, `ConfirmDialog`, `ActionMenu`,
`Badge`, `useServerTable`, `useDebouncedValue` — the same foundation
every master-data page composes. No attribute builders, variants,
templates, bundles, pricing-rule engines, or PIM-style attribute
management — none of that exists in jdk_clean either (audit #14), and
none is justified at ~20 products. Category and Unit of Measure are
rendered as `<select>` dropdowns of the caller's own active records
(`GET /api/categories`, `GET /api/units-of-measure`), reusing those
existing endpoints rather than a new lookup.

Field grouping in the form, per the user's own spec:

```text
General
    Product Code, Product Name, Category, UoM, Description

Commercial
    Default Selling Price

Planning
    Manufacturing Lead Time, Customer Lead Time

Status
    Active / Inactive
```

## 12. Database integrity

`products` table: primary key, `organisation_id` FK to `organisations`
(`ondelete=RESTRICT`, indexed), `category_id` FK to `categories`
(`ondelete=RESTRICT`, indexed), `unit_of_measure_id` FK to
`units_of_measure` (`ondelete=RESTRICT`, indexed), `code`/`name`/
`selling_price` required, unique per `(organisation_id, code)` and
`(organisation_id, name)`. `selling_price` and both lead-time fields are
validated non-negative at the schema layer (defense in depth — the
database itself doesn't enforce a numeric range on SQLite, so this is
application-level, matching every other numeric validation in this
codebase).

## 13. Historical data integrity

Documented as a binding rule for every future consumer, per #4/#6 above:
changing Product's selling price, Customer Lead Time, or Manufacturing
Lead Time must never rewrite a historical quotation, order, or
feasibility/production decision. Any module that needs to preserve a
Product value at the time of a transaction must snapshot that value onto
its own transaction row — never a live FK-derived read of Product.
Deactivating a Product must never remove it from historical records
(no hard delete exists to do so in the first place).

## 14. Access and security

Reuses existing RBAC (`require_admin`) exactly like Category/Unit/
Supplier — no Product-specific authorization layer, and no department-
permission matrix (jdk_clean's own gate for this module, per audit #13)
since Product has no ownership dimension. Read
(`GET /api/products`, `GET /api/products/{id}`) is open to any
authenticated organisation member; create/edit/activate-deactivate are
admin-gated. Organisation isolation and FK validation (category/unit must
belong to the caller's own organisation) are enforced server-side on
every mutation — the frontend is never the security boundary.

## 15. Performance

No caching layer, no specialised search infrastructure — the expected
volume (~20 rows per organisation) doesn't justify it, same reasoning as
every prior master. The common list/pagination/search infrastructure is
reused unchanged.

## 16. Integration

No consuming module (Feasibility, Quotation, Order, BOM, Production,
Inventory, Delivery) exists yet in this codebase. This module establishes
the authoritative product record, plus the two documented historical-
integrity rules (price and lead-time snapshotting), for those modules to
build against when they land, per Principle 5.

## 17. Acceptance criteria

**Audit**: `jdk_clean` audited — a real, fairly disciplined ~20-field
Product exists there, but Customer Lead Time doesn't exist at all (a
confirmed gap) and Manufacturing Lead Time is only a rate-based capacity
engine, never a literal field (see
[`../audit/PRODUCTS_AUDIT.md`](../audit/PRODUCTS_AUDIT.md)); `jdk_erp`
audited — confirmed fully greenfield before implementation.

**Data**: identity defined (id/code/name/category_id/unit_of_measure_id/
description/selling_price/manufacturing_lead_time_days/
customer_lead_time_days/is_active); code and name required and unique
per organisation; code immutable after creation; category and unit of
measure reference their authoritative masters and must be active in the
caller's own organisation; lead-time fields have the confirmed, distinct
business meanings documented in #4/#5; no duplicated stock quantity
exists on Product.

**Sales/Feasibility**: Customer Lead Time is available for a future Sales
consumer; Manufacturing Lead Time is available for a future Feasibility
consumer; their meanings remain distinct per #5; the historical-integrity
rule for both is documented as binding on whichever module consumes them
first.

**Production**: Product can participate in a future BOM relationship
without any composition duplicated onto it; production execution data
stays entirely outside Product.

**Inventory**: Product identifies the finished product only; no stock
quantity field exists on it.

**Lifecycle**: active/inactive works; no hard delete exists; historical
records remain valid (there being none yet to break).

**Security**: organisation scope is server-enforced; RBAC
(`require_admin`) is server-enforced; no client-supplied organisation
value is trusted; a cross-organisation category/unit reference is
rejected with 422, a cross-organisation product id 404s.

**UX**: existing common UI components reused with no product-specific
duplicate; create/edit validation surfaces inline (blank code/name,
negative price/lead-time, inactive or cross-organisation category/unit,
duplicate code/name); active/inactive shown via the shared `Badge`; a
non-admin sees the same list with no mutating controls.

**Testing**: create, edit (including the immutable-code case), activate/
deactivate, duplicate code/name rejection (409), invalid/inactive/
cross-organisation category or unit rejection (422), invalid lead-time/
price values (422), unauthorized access (401/403), cross-organisation
access (404), and the price-read-is-always-current pin-down test
documenting the snapshotting obligation for future consumers.

## 18. The structure being built

```text
                    ┌─────────────────┐
                    │     Product     │
                    │                 │
                    │ Code / Name     │
                    │ Category / UoM  │
                    │ Selling Price   │
                    │ Mfg Lead Time   │
                    │ Customer Lead   │
                    │   Time          │
                    │ Status          │
                    │ Organisation    │
                    └────────┬────────┘
                             │
       ┌──────────┬──────────┼──────────┬──────────┐
       ▼          ▼          ▼          ▼          ▼
   Feasibility Quotation   Order       BOM     Inventory
   (not yet)  (not yet)  (not yet)  (not yet)  (not yet)
```

## 19. Most important architectural rule

Product is the authoritative definition of what JDK sells and
manufactures — not a generic ERP/PIM product-information system. Keep
the boundaries explicit: Product holds what it is, how it's classified,
and two distinct reference values (Customer Lead Time for Sales
commitments, Manufacturing Lead Time for feasibility/planning) — never a
delivery-calculation engine, a capacity-scheduling engine, BOM
composition, or stock quantity. Every one of those belongs to its own
future module, referencing Product by foreign key.

## Implementation approach

Per [`../ENGINEERING_PRINCIPLES.md`](../ENGINEERING_PRINCIPLES.md) §16
("Audit before changing"): see
[`../audit/PRODUCTS_AUDIT.md`](../audit/PRODUCTS_AUDIT.md). Structurally
mirrors Category/Unit/Supplier's admin-gated CRUD shape (no permission-
scope engine — Product has no ownership dimension), with two new
elements: `code` is caller-supplied and immutable (unlike Customer/
Supplier's auto-generated codes, preserving jdk_clean's real established
behaviour), and `category_id`/`unit_of_measure_id` are the first
cross-master-data foreign keys in this codebase, validated active and
same-organisation on every create/update. `MASTER_DATA_MODULE` (the same
shared audit-module constant every prior Phase 2 entity logs under) is
reused again, not a new `PRODUCT_MODULE` constant.
