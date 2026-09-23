# Warehouses / Storage Locations — Audit of jdk_clean

Audited before building `docs/modules/warehouses.md`, per Principle 5
(reuse before creating) and Principle 16 (audit before changing). Scoped
strictly as master data — a single warehouse's identity plus a
configurable total storage capacity — never the full Inventory/Stock
Ledger/Procurement/Production/Delivery system, none of which exist in
jdk_erp yet.

## 1. Does a warehouse/location table exist in jdk_clean?

**No.** A case-insensitive search of `schema.sql` and every migration
finds no `warehouses`, `locations`, or `storage_locations` table
anywhere. `finished_goods_inventory` (product_id unique FK,
`quantity_on_hand`/`quantity_reserved`) and `raw_material_inventory`
(raw_material_id unique FK, same shape), plus the shared `stock_movements`
ledger, all key off `item_type`/`item_id` with **no location column of
any kind**. This is the same "singleton via absence" pattern jdk_clean
uses elsewhere (a single Machine row, no multi-plant support): inventory
is implicitly single-warehouse because there is nowhere in the schema to
record a second one.

The only place the word "warehouse" appears as a concept at all is one
row in jdk_clean's generic `departments` table (`sales`/`procurement`/
`warehouse`/`production`), used purely to gate which users see
warehouse-scoped dashboard notifications through the department-
permission matrix. It has no identity, capacity, or lifecycle of its own
— it is a permission label, not a master-data row.

**This means jdk_erp's Warehouse master is a genuinely new concept,
built directly from the spec — there is no jdk_clean design to reuse or
diverge from for the entity itself.**

## 2. Storage area/capacity concept anywhere

**Not found, with one narrow, confirmed-dead exception.** An exhaustive
case-insensitive search for `area`, `capacity`, `footprint`, `volume`,
`sqm`, `sqft`, `space_required`, `storage_capacity` across the entire
repository (backend, frontend, mobile) finds:

- Every real `capacity`/`area` hit traces to **machine/production time
  capacity** (`capacity_service.py`, `feasibility_service.py` — the same
  daily machine-hours/worker-hours scheduling already documented in
  `MACHINES_AUDIT.md`), or incidental English words.
- `volume` hits are transaction-volume or a UoM *category* enum
  (`weight`/`count`/`volume`) — a measurement classification, not a
  storage-space field.
- The one storage-adjacent field: `raw_materials.storage_location`
  (VARCHAR(100), nullable) — a free-text bin/shelf label (e.g. "Aisle
  3"), not an FK, not an area/capacity value, and explicitly confirmed
  by the surrounding model comments as "not read by any business
  logic." Rendered as a plain read-only text input on the frontend.
- `Product` and `Machine` have no storage-area/footprint field at all.

No `sqm`, `sqft`, `footprint`, or `space_required` string exists
anywhere in jdk_clean.

## 3. Does inventory reference a warehouse_id?

Moot — there is no warehouse/location table to reference. Inventory and
stock movements carry zero location dimension: one implicit warehouse
for the whole system.

## 4. Evidence JDK's real business calculates storage area?

**None.** `capacity_service.py` and every caller (feasibility, production
readiness, order auto-scheduling) is explicitly about machine-hours/
worker-hours, never square footage or physical space. No comment, doc,
or service anywhere in jdk_clean mentions storage space, floor area, or
a per-unit space requirement.

**This is a genuine zero-prior-art area**, the same situation Customer
Lead Time and Manufacturing Lead Time were in during the Products audit
— any storage-area-per-unit field on Product/RawMaterial would be
designed entirely from scratch, with no reference implementation to
reuse or contradict, and (critically) no Inventory/Stock Ledger yet in
jdk_erp to supply the live stock quantities such a field would need to
be multiplied against. Even if the field existed today, the "required
area" calculation would be permanently inert without real stock
quantities.

**Decision: do not add a storage-area-requirement field to Product or
RawMaterial now.** Zero evidence of a real business need, and the field
would be unusable regardless until Inventory exists. Documented in the
module spec as a deferred decision for whenever Inventory/Stock Ledger
is built and this need can be evaluated against real usage.

## 5. Hierarchical location (zones/aisles/racks/bins)?

Absent entirely — no stub table, enum, or column for any location
hierarchy anywhere in jdk_clean. Confirms the spec's own instruction not
to build one is not fighting against any existing jdk_clean pattern
either.

## 6. Access and permissions

No warehouse *entity* exists to gate. "Warehouse" as a department row is
gated the same way every department is, through the generic department-
permission matrix. **Decision**: since there is no entity-level gate to
diverge from, Warehouse reuses the plain `require_admin`-gated shape
every other jdk_erp master with no ownership dimension already uses.

## 7. Frontend

`WarehouseHomePage.tsx`/`WarehouseDashboardCharts.tsx` exist but are a
**departmental dashboard** (inventory value, low-stock items,
warehouse-scoped notifications, all pulling from existing dashboard/
inventory/notification endpoints) — not a warehouse-master CRUD page.
No detail/edit form, no capacity meter, no location picker anywhere.
Nothing to reuse or explicitly avoid here; this module's own admin UI is
built fresh, matching Category/Machine's flat-list precedent.

## 8. Lifecycle

Not applicable in jdk_clean — no warehouse row-level entity exists to
have a lifecycle, delete guard, or singleton check.

**Decision for jdk_erp**: a plain `is_active` boolean, no hard delete
(consistent with every master), no singleton constraint (ordinary CRUD
already produces "exactly one" today, same reasoning as Machine/
ProductionLine). No special guard against deactivating the only active
warehouse is built yet either — there are no inventory operations in
this codebase for that to break (Inventory doesn't exist). That guard is
documented as a binding rule for whichever future Inventory module
actually depends on an active warehouse to record movements against.

## Bottom line

jdk_clean has zero warehouse/location identity table and zero evidence
of a per-material/per-product storage-area concept — "warehouse" there
is purely a department/permission label. jdk_erp's Warehouse master is
therefore built fresh, directly against the user's spec: identity
(code/name/status) plus one structured, configurable capacity value
(`total_usable_storage_area` + `storage_area_unit_of_measure_id`,
reusing the existing UnitOfMeasure master, the same pattern Machine
already established for its own capacity). No per-material storage
requirement, no required/available-area calculation, no warehouse-in/
out, no stock ledger, no hierarchical locations, and no geographic/
logistics fields are built — each is either unevidenced, or has no
prerequisite infrastructure in jdk_erp (Inventory/Procurement/Production/
Delivery are all unbuilt), and each is documented in the module spec as
a binding target for whichever future module needs it.
