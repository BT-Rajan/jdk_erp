# JDK Master Data: Warehouses / Storage Locations

Eighth entity of [`../ROADMAP.md`](../ROADMAP.md) Phase 2 — Master Data,
following Categories, Units of Measure, Customers, Suppliers, Products,
Raw Materials, and Machines/Production Lines. Warehouse is the
authoritative definition of the physical storage area inside the JDK
factory. JDK currently has 1 warehouse, no multi-warehouse or logistics
requirement — this module is explicitly not a Warehouse Management
System.

## 1. Purpose

Provide the foundation for raw-material storage, finished-goods storage,
and storage-capacity reference — not a generic logistics/WMS module. No
geographic warehouse management, no transportation planning, no
multi-warehouse support.

## 2. Warehouse definition

id, code (required, manually entered, immutable after creation — a
deliberate jdk_erp convention here, since jdk_clean has no such entity to
audit; the same treatment already given to Product/RawMaterial/Machine's
own stable identifiers), name (required), active/inactive state,
organisation, timestamps. No address, country, region, GPS, transport
zone, warehouse type, shipping carrier, operating hours, temperature
zone, or storage class — jdk_clean has none of these either (see
[`../audit/WAREHOUSES_AUDIT.md`](../audit/WAREHOUSES_AUDIT.md) #1), and
none has a proven JDK requirement.

## 3. Storage area

The one important addition beyond bare identity: `total_usable_storage_area`
+ `storage_area_unit_of_measure_id` — a structured, configurable total
capacity value, reusing jdk_erp's own existing UnitOfMeasure master
(validated active and same-organisation on every write, the same
treatment Machine already gives its own `capacity_unit_of_measure_id`)
rather than a free-text string or a hard-coded unit. An authorised user
can reconfigure the total area via a plain `PATCH`, no code change
required — the same reconfiguration pattern Machine's capacity already
established.

## 4. Storage capacity boundary

**Not built**: the `Total Usable Area − Required/Occupied Area =
Available Area` calculation. jdk_clean has zero evidence of a
per-material/per-product storage-area-requirement concept anywhere — the
only near-miss is `raw_materials.storage_location`, a free-text bin
label explicitly confirmed unused by any business logic (audit #2). Even
if such a field existed, "required area" cannot be computed today
regardless: there is no Inventory/Stock Ledger in this codebase yet to
supply the live stock quantities the calculation needs. This module
therefore stores only the *total* configured capacity; documented here
as the binding target formula for whenever Inventory exists:

```text
Total Usable Storage Area
-
Current Required/Occupied Storage Area (derived from live stock × per-unit storage requirement)
=
Available Storage Area
```

Never a manually-maintained second source of truth for occupied area —
whichever future Inventory module computes this must derive it live,
never store it as an editable field.

## 5. Raw Material storage requirement

**Not built.** The audit found no evidence anywhere in jdk_clean of a
per-material storage-area-requirement (e.g. "X m² per tonne") — a
genuine zero-prior-art area, the same situation Customer/Manufacturing
Lead Time were in during the Products audit. Adding a field with no
proven need and no Inventory to consume it would be pure speculation.
**Decision: defer.** If JDK's real business is later proven to calculate
storage area per material, add a storage-requirement field to
`RawMaterial` at that time, against that module's own audit — not now.

## 6. Finished Goods storage requirement

Same decision as #5, applied to `Product`: no evidence, no consumer,
deferred until proven necessary.

## 7. Storage calculation

Not implemented — see #4. The conceptual formula
(`required quantity × storage requirement per unit = required storage
area`) is documented here as the binding target for whenever both a
storage-requirement field (#5/#6) and live stock quantities (Inventory)
exist to compute it from. Not invented or approximated now.

## 8. Warehouse IN / stock receipt

Not built — Purchase Order, Receipt, and Inventory don't exist in this
codebase. The Warehouse master itself must never record a transaction;
it only ever provides the authoritative location a future inventory
movement references. Documented as the binding chain for whenever those
modules exist: `Purchase Order → Receipt → Raw Material Warehouse IN →
Raw Material Inventory`, and `Production → QC Accepted → Finished Goods
Warehouse IN → Finished Goods Inventory`.

## 9. Warehouse OUT / stock issue

Not built, same reasoning as #8. Documented chain:
`Raw Material Inventory → Warehouse OUT / Material Issue → Production`,
and `Finished Goods Inventory → Warehouse OUT → Delivery → Customer`.

## 10. One authoritative stock ledger

Not built — no Stock Ledger exists in jdk_erp yet. Documented as a
binding rule for whenever it is: `Opening Stock + Receipts − Issues ±
Adjustments = Current Stock`, with the Stock Ledger as the sole authority
for quantity. No module (Warehouse included) may maintain a second,
independently-editable quantity field.

## 11. Raw Material inventory

Not built. Documented relationship for whenever Inventory exists:
`RawMaterial → Inventory → Warehouse → Stock Quantity` — RawMaterial
defines the material, Inventory defines the quantity, Warehouse defines
where it's stored. jdk_clean's own shape (a `raw_material_inventory`
snapshot table plus a `stock_movements` ledger, both with zero location
dimension today) is documented in the audit (#1) as the starting point,
extended with a `warehouse_id` when this module's future consumer is
built.

## 12. Finished Goods inventory

Same structure as #11, for `Product`. Documented for Sales: `Customer
Order → Check Finished Goods Stock → Sufficient (use existing stock) /
Insufficient (Production required)` — the same rule already documented
in `docs/modules/products.md` #6's price-boundary discussion, restated
here as the future Inventory module's responsibility to answer.

## 13. Production relationship

Not built — Production doesn't exist in this codebase. Warehouse must
never carry production-order state, scheduled orders, actual production
quantity, actual timing, operator activity, or QC result — all future
Production concerns.

## 14. Procurement relationship

Not built — Purchase Order/Receipt don't exist. Documented chain:
`Supplier → PO → Receipt → Warehouse IN → Raw Material Inventory`.
Warehouse must never create purchase orders; PO must never maintain its
own independent stock quantity.

## 15. Sales and Delivery relationship

Not built — Sales/Delivery don't exist. Documented chain: `Product →
Finished Goods Stock → Sales Order → Ready to Ship → Delivery →
Warehouse OUT`. Delivery must reduce stock only through the authoritative
inventory transaction, never a second quantity of its own.

## 16. Storage capacity vs. stock quantity

A binding conceptual distinction for every future consumer: stock
quantity answers "how much do we have," storage requirement answers "how
much area does that quantity need," and warehouse capacity answers "how
much usable area do we have." These must never be mixed into a single
"capacity" field — Warehouse holds only the third value
(`total_usable_storage_area`) today; the other two depend on modules
that don't exist yet.

## 17. Storage availability and transactions

Not built — there is no inbound-movement transaction yet to check
capacity against. Documented as the binding integration point for
whenever Procurement/Production exist: a planned receipt or production
run may need to check available warehouse area before proceeding, per
whatever exception/approval rule the business actually has (not invented
here). Capacity must never automatically block a transaction unless
that's an established business rule discovered at that module's own
audit.

## 18. Warehouse locations

No hierarchical location system (zone → aisle → rack → bin) is built —
jdk_clean has none either (audit #5), and JDK has no current requirement
for one. For now: `Factory Warehouse → Raw Material Stock / Finished
Goods Stock` is the complete structure. If an internal-location
requirement is proven later, it can be added without corrupting this
model, since Warehouse already has its own identity separate from
Inventory.

## 19. No geographic or logistics model

Explicitly out of scope, matching jdk_clean's own complete absence of
any such feature: multiple geographic warehouses, addresses, GPS,
inter-warehouse transfers, transportation planning, carrier management,
route planning, shipping zones, operating calendars, cold storage,
temperature monitoring, or storage-condition management. None of this is
added for theoretical future scalability.

## 20. Lifecycle

```text
Active
  │
  ▼
Inactive
```

No delete endpoint — Warehouses are never hard-deleted, matching every
other master. No delete guard is needed yet either: nothing in jdk_erp
references `warehouses` (Inventory/Procurement/Production/Delivery are
all unbuilt). No guard against deactivating the only active warehouse is
built yet either, since there are no inventory operations for that to
break — this is documented as a binding rule for whichever future
Inventory module actually depends on an active warehouse to record
movements against: it must prevent (or require explicit confirmation
for) deactivating the last active warehouse once real inventory
operations exist to be broken by it.

## 21. Organisation scope

Warehouses are organisation-owned records (`OrganisationScopedMixin`,
same as every other master). jdk_clean has no organisation/tenant-
scoping concept anywhere (consistent with every prior audit) — no
precedent to follow, only jdk_erp's own established convention to apply.

## 22. Administration UX

A single flat list page (`DataTable`/`FormDialog`/`ConfirmDialog`/
`ActionMenu`/`Badge`), the same granularity as Machine/ProductionLine —
a configuration-level master, not an operational dashboard. The form
includes a Storage Area Unit dropdown (reusing `GET /api/units-of-measure`,
the same pattern Machine's Capacity Unit dropdown already established).
No raw-material/finished-goods stock summaries, no inbound/outbound
panels, no utilisation meter — none of that data exists yet (Inventory
is unbuilt); a placeholder with nothing to show would be dead UI, the
same reasoning Raw Materials already applied to deferring "Used in
BOMs"/"Current Stock" summaries.

## 23. Database integrity

`warehouses`: primary key, `organisation_id` FK (`RESTRICT`, indexed),
`storage_area_unit_of_measure_id` FK (`RESTRICT`, indexed), `code`/`name`
required and unique per organisation, `total_usable_storage_area`
validated strictly positive at the schema layer, never stored as
free-text. `code` is never hard-coded as a magic constant (e.g.
`warehouse_id = 1`) anywhere — even with exactly one row today, the
warehouse has a proper database identity any future consumer references
by foreign key.

## 24. Inventory integrity

Not applicable yet — no inventory movement table exists. Documented as
a binding rule for whenever one is built: every inventory movement must
reference the Product or RawMaterial, the Warehouse, the quantity, the
UoM, the movement type, and the related business transaction (Receipt,
Production, Delivery) — reusing/hardening whatever inventory foundation
is built then, never a second, parallel ledger.

## 25. Transaction boundary

Warehouse owns: identity, storage capacity configuration, status,
organisation relationship. It does not own: purchase orders, receipts,
sales orders, production orders, delivery notes, stock quantities, stock
movements, or material requirements — all transactional modules, all
unbuilt, all documented above as future consumers of this master.

## 26. Access and security

Reuses existing RBAC (`require_admin`) exactly like every other master —
no Warehouse-specific authorization layer. There is no jdk_clean gate to
diverge from here (audit #6) — "warehouse" in jdk_clean is only a
department-permission label, not an entity with its own gate. Read is
open to any authenticated organisation member; create/edit/activate-
deactivate are admin-gated. A future Inventory module's own transaction
permissions are a separate concern from this master's configuration
permissions — viewing inventory must never imply the ability to
reconfigure warehouse capacity.

## 27. Performance

No caching, no search infrastructure, no warehouse microservices, no
asynchronous inventory processing, no location engines — the expected
volume (1 warehouse per organisation today) doesn't justify any of it.
Whichever future Inventory module queries against `Warehouse` is
responsible for its own indexed, N+1-free access patterns.

## 28. Integration

No consuming module (Inventory, Procurement, Production, Sales,
Delivery) exists yet in this codebase. This module establishes the
authoritative warehouse identity and configured total storage capacity,
plus every documented boundary/deferred-decision above, for those
modules to build against when they land. No downstream module may
maintain its own warehouse or location definition.

## 29. Acceptance criteria

**Audit**: `jdk_clean` audited — it has no warehouse/location entity at
all ("warehouse" is purely a department-permission label) and no
storage-area concept anywhere except one confirmed-dead free-text field
(see
[`../audit/WAREHOUSES_AUDIT.md`](../audit/WAREHOUSES_AUDIT.md));
`jdk_erp` audited — confirmed fully greenfield before implementation.
Per-material/per-product storage-requirement need ruled out for lack of
evidence, not overlooked.

**Master**: one authoritative warehouse exists; code/name/status are
defined; organisation scope is enforced; total storage capacity is
configurable via a structured quantity + unit.

**Storage**: total usable storage area can be configured; the area unit
is explicit (reusing the UnitOfMeasure master, never hard-coded);
required/occupied/available area are not built (no evidence, no
Inventory to derive them from) — documented as deferred, not silently
omitted.

**Inventory/Procurement/Production/Sales/Delivery**: none built yet;
each integration point and boundary rule is documented as binding for
when that module lands.

**Lifecycle**: no hard delete; no delete guard needed yet (nothing
references `warehouses`); the "don't casually disable the only
warehouse" concern is documented as a future Inventory-module
responsibility, since no inventory operations exist yet to protect.

**Security**: organisation scope is server-enforced; RBAC
(`require_admin`) is server-enforced; a cross-organisation or inactive
unit-of-measure reference is rejected with 422; a cross-organisation
warehouse id 404s.

**Testing**: create/configure warehouse (with structured capacity),
reconfigure capacity without a code change, duplicate code/name
rejection (409), inactive/cross-organisation unit-of-measure rejection
(422), non-positive area rejection (422), immutable code (a `code` sent
on `PATCH` is silently ignored), activate/deactivate, unauthorized
access (401/403), cross-organisation access (404).

## 30. Most important architectural rule

Warehouse is the authoritative physical storage location and capacity
reference — not a generic Warehouse Management System. It answers
exactly one question today: *where is our storage, and how much usable
area does it have?* Every other question this module's spec raises —
how much area is required, how much is available, how stock moves in
and out, how procurement/production/sales/delivery affect it — belongs
to a future Inventory/Procurement/Production/Sales module, each of which
must reference this one authoritative Warehouse, never invent its own.
Keep the one warehouse simple; make its future relationships and
inventory calculations authoritative when those modules are actually
built.

## Implementation approach

Per [`../ENGINEERING_PRINCIPLES.md`](../ENGINEERING_PRINCIPLES.md) §16
("Audit before changing"): see
[`../audit/WAREHOUSES_AUDIT.md`](../audit/WAREHOUSES_AUDIT.md). `Warehouse`
mirrors Machine's shape closely — caller-supplied immutable code,
required active-and-same-organisation UnitOfMeasure FK validation, and a
capacity value reconfigurable via a plain `PATCH` with no code change —
the same pattern applied to a single structured field
(`total_usable_storage_area`) instead of Machine's three-part rate.
`MASTER_DATA_MODULE` (the same shared audit-module constant every prior
Phase 2 entity logs under) is reused again, not a new module constant.
