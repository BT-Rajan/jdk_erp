# JDK Master Data: Raw Materials

Sixth entity of [`../ROADMAP.md`](../ROADMAP.md) Phase 2 — Master Data,
following Categories, Units of Measure, Customers, Suppliers, and
Products. Raw Material is the authoritative material identity bridging
two chains:

```text
Supplier -> Raw Material -> Purchase Order -> Receipt -> Inventory
Product -> BOM -> Raw Material -> Production
```

JDK has ~5 raw materials — the master itself stays as lean as Category/
Unit/Supplier. The relational depth the user asked for concentrates
entirely in the Supplier ↔ Raw Material relationship, the one link both
sides of which already exist in jdk_erp today.

## 1. Purpose

Provide the single authoritative material identity every downstream
module (Supplier relationships now; BOM, Purchase Order, Receipt,
Production, Inventory later) references by foreign key — never a
free-text material name, and never a second, parallel material
identifier invented by any consuming module.

## 2. Raw Material record

id, code (required, system-generated, immutable after creation), name
(required), category (required FK to the authoritative Category master),
unit of measure (required FK to the authoritative UnitOfMeasure master),
description (optional — also where a business-critical specification
goes, as free text; see #16 below), reference cost (optional, current/
default only), active/inactive state, organisation ownership,
created/updated timestamps.

Deliberately excluded, all confirmed against
[`../audit/RAW_MATERIALS_AUDIT.md`](../audit/RAW_MATERIALS_AUDIT.md):
material type, manufacturer/manufacturer part number, barcode, weight
(none consumed by any real behaviour in jdk_clean), the generic
`properties` JSON attribute bag (confirmed "not read by any business
logic" — see #16), inspection/certificate/QC flags (present in jdk_clean
but never actually enforced at receipt), storage location, and
reorder/safety-stock/maximum-stock thresholds (all are Inventory
concerns — Inventory doesn't exist in jdk_erp yet; add them there, not
here, when it's built).

## 3. Material identity

One authoritative identity per material — `code`/`name`/`category_id`/
`unit_of_measure_id`/`description`/`is_active`/`organisation_id`. Every
downstream reference (Supplier relationship now; BOM/PO/Receipt/
Inventory/Production later) points at this same row by foreign key.
There must never be a second material identifier minted by a consuming
module (a "PO material id," an "inventory material id," etc.) — this is
the one purpose this master exists to serve.

**Raw Material code**: system-generated and immutable after creation
(`app/core/id_formats.RAW_MATERIAL_CODE`: prefix `1` + a 5-digit
per-organisation sequence) — per explicit user instruction that every
Phase 2 master's code be auto-assigned, superseding this section's
original decision to match jdk_clean's own manually-assigned code
(audit #2).

## 4. Category and Unit of Measure

Both required FKs to jdk_erp's own existing masters, validated active
and same-organisation on every create/update — never free-text or an
enum. jdk_clean itself briefly built a real units-of-measure table then
reverted it (audit #3, the same history already documented for Product)
— that reversal is not followed here. The UoM defines the one quantity
meaning for this material throughout every future consumer (procurement,
receipt, inventory, BOM, material requirement, allocation, production
consumption) — there is no per-module reinterpretation.

## 5. Purchase Unit of Measure

**Not built.** jdk_clean has no purchase-vs-stock UoM distinction or
conversion factor anywhere, despite having live procurement (audit #4) —
a confirmed gap, not prior art. Per the spec's own instruction, this must
not be built speculatively. If JDK's actual procurement process is later
proven to need "stocked in KG, purchased in BAG," the conversion belongs
on `SupplierMaterial` (per-relationship, since it's inherently
supplier/packaging-specific — Supplier A might sell in bags, Supplier B
in bulk), not as a second UoM on Raw Material itself.

## 5a. Material-specific BOM conversion

**Built for BOM** ([`boms.md`](boms.md) §3,
[`../audit/BOMS_AUDIT.md`](../audit/BOMS_AUDIT.md) §5) — distinct from
§5's Purchase UoM (which stays unbuilt, no evidence). A material may
optionally carry `alternate_conversion_unit_of_measure_id` +
`alternate_conversion_factor`, meaning "1 [this material's own
`unit_of_measure`] = `alternate_conversion_factor`
[`alternate_conversion_unit_of_measure`]" — e.g. "1 litre of this
Material = 1.25 kg" or "1 bag of this Material = 25 kg." Both nullable,
always both-set-or-both-null, and the alternate unit must differ from
the material's own unit. This is deliberately scoped to *this one
material* — never a property of the unit itself (that would repeat
jdk_clean's own conflated `factor_to_base` mistake, see
`docs/modules/units_of_measure.md` §5) — and exists solely to let BOM
validate and convert a Product↔Material relationship; it has no meaning
or consumer outside that.

## 6. Supplier relationship

The one relationship built with real depth, via a new `SupplierMaterial`
join table — because both Supplier and Raw Material already exist in
jdk_erp, this is genuinely buildable today (unlike BOM/PO/Receipt/
Inventory, all deferred per #10–#13 below). Reproduces jdk_clean's own
well-designed `supplier_materials` shape (audit #5) with the columns that
would be dead weight without Purchase Order/Receipt removed:

- `supplier_id`, `raw_material_id` — both required, CASCADE on delete
  (a pure relationship row, no standalone value once either side is
  truly gone — same reasoning as this codebase's `UserTeam`).
- `supplier_material_code` — the *supplier's own* SKU for this material,
  genuinely distinct from the material's own `code`.
- `purchase_price` — a reference/default value (see #7's price boundary
  below), optional (a relationship may exist before pricing is
  finalized).
- `lead_time_days` — this supplier's lead time for this material,
  distinct from anything on Product (Product's lead-time fields are
  about finished goods and customer commitments; this is procurement's
  own, unrelated concept).
- `moq` (minimum order quantity), `max_supply_quantity` — both optional,
  genuine supplier-capacity constraints jdk_clean actively uses.
- `is_preferred` — at most one preferred supplier per material,
  **enforced service-side only** (setting one silently un-sets any
  other), matching jdk_clean's own real, deliberate choice exactly — no
  DB constraint, no rejected write.
- `is_active` — pausing a relationship without severing it.

A material may have zero, one, or many suppliers — no minimum is
enforced, matching jdk_clean's confirmed real behaviour exactly (a
material with no suppliers linked yet is a normal state, not an error).

**Not reproduced from jdk_clean**: `currency` (this codebase's
`Organisation.currency` already covers it — no evidence multi-currency
procurement is needed), `onboarded_at`/`last_transaction_at` (both are
only ever written by an actual Purchase Order receipt event in
jdk_clean — that module doesn't exist here yet, so these would be dead
columns with no writer), and the separate pause-vs-sever (`status` vs
`deleted_at`) distinction (nothing yet needs it, since no transaction
table exists to reference a severed relationship historically — severing
here is a real `DELETE`, pausing is `is_active`).

## 7. Supplier-specific information and the price boundary

Supplier-specific data lives on the relationship (`SupplierMaterial`),
never duplicated as columns on Raw Material itself — there is no
`Supplier Name`/`Supplier Price`/`Supplier Lead Time` on `RawMaterial`.

`purchase_price` on `SupplierMaterial` is a reference/default value only.
jdk_clean itself never actually wires this into Purchase Order line
pricing (PO lines there default from `RawMaterial.unit_cost` instead — a
real inconsistency in jdk_clean, noted in the audit #5 but not something
to fix now, since no PO module exists here to wire it into either way).
The binding rule documented for whenever Purchase Order is built: a PO
line must snapshot its own price at creation time — never a live read of
`SupplierMaterial.purchase_price` or `RawMaterial.reference_cost` — so a
later change to either can never rewrite a historical purchase order.

## 8. Product → BOM → Raw Material relationship

**Built** — see [`boms.md`](boms.md). A `BomComponent` references the
authoritative Raw Material by FK (`RESTRICT`) and owns its own required
quantity, in the material's own unit; `RawMaterial` still carries no
"quantity required per product" field of any kind. jdk_clean's own BOM
shape (`bom_lines.component_type` polymorphic raw_material/product) is
the template for the header/line split (`docs/audit/BOMS_AUDIT.md` §1)
— the polymorphic product-as-component half is deliberately not
reproduced (no proven sub-assembly need; see that audit's §1).

## 9. BOM quantity boundary

Raw Material carries no quantity-required-per-product,
per-batch, wastage percentage, allocation, or consumption field, now
that BOM exists to prove the boundary against: those are BOM/production
concepts. `RM-001 Cement` means one authoritative material; how much of
it Product A's BOM needs, versus Product B's, are two independent
`BomComponent` facts, never stored on `RawMaterial` itself.

## 10. Procurement relationship

Not built yet — Purchase Order and Receipt don't exist in this
codebase. Confirmed zero prerequisite infrastructure in jdk_erp (audit's
own "buildability guidance"). Documented as the binding chain for
whenever they're built: Material Requirement → Purchase Order → Receipt
→ Raw Material Inventory, each a distinct record, never collapsed into
one — a PO records what was ordered, a Receipt records what was actually
received, Inventory records what currently exists; Raw Material only
ever identifies what the material itself is.

## 11. Inventory relationship

Not built yet — Inventory doesn't exist in this codebase. Confirmed
`RawMaterial` carries **no quantity field of any kind** — this is
enforced now, before Inventory exists, precisely so nothing is ever
tempted to add one later "for convenience." jdk_clean's own shape (a
materialized current-quantity snapshot table plus a full movement
ledger, both separate from `raw_materials`) is documented in the audit
(#9) as the target design for when Inventory is built. If a future UI
shows current stock on the Raw Material page, it must be a derived,
read-only value fetched from that future Inventory endpoint — never a
column on this table.

## 12. Inventory unit integrity

Restated as a binding rule for whenever Procurement/Inventory exist: a
material's quantity must mean the same thing (this material's
`unit_of_measure_id`) at every stage — PO, receipt, inventory, BOM,
material requirement, allocation, production consumption — with no
silent reinterpretation between modules. Any unit conversion (e.g. a
supplier's purchase unit differing from the stock unit) must be explicit
and attributable to a specific relationship (see #5's Purchase UoM
decision), never assumed.

## 13. Production relationship

Not built yet — Production doesn't exist in this codebase. Confirmed
zero prerequisite infrastructure. `RawMaterial` must never carry
allocated/consumed quantity, production order status, machine
assignment, schedule, QC result, or batch state — all Production
concerns, documented here as a boundary for whenever that module is
built, not something enforced by any code today (there being nothing yet
to violate it).

## 14. Material availability and feasibility

Not built yet. Documented as the future resolution chain: Product → BOM
→ Raw Material → Inventory/Availability. Raw Material provides identity
only; availability computation belongs to Inventory/Planning once built,
never to this master.

## 15. Material availability must not become procurement logic

No automatic replenishment, reorder points, MRP, or purchasing automation
exists or is planned here — none of that has a proven JDK requirement
today (audit confirms jdk_clean's own reorder-point fields are
Inventory-side thresholds only, never wired to any automatic PO
creation). If JDK's real procurement process is later proven to need
this, it belongs to a future Procurement module's own audit, not this
one.

## 16. Material specifications

`description` is where a business-critical specification goes, as free
text — no separate `grade`/`specification`/generic-attribute-bag field.
jdk_clean's own `properties` JSON bag is confirmed unused by any business
logic (audit #1); per the spec's own instruction, two operationally
different materials should be distinct authoritative records (their own
`code`/`name`) rather than variants distinguished by free-form
attributes.

## 17. Lifecycle

```text
Active
  │
  ▼
Inactive
```

No delete endpoint — Raw Materials are never hard-deleted, matching
every other master. No delete guard is needed yet either: nothing in
jdk_erp references `raw_materials` (BOM/PO/Receipt/Production/Inventory
are all unbuilt) — unlike jdk_clean, which has real consumers but, per
the audit (#13), *still* has no such guard, a gap explicitly not
repeated: whichever module becomes the first real consumer is
responsible for respecting `is_active` at selection time. Deactivating a
material is entirely independent of its `SupplierMaterial` relationships
— it never silently deactivates or removes them as a side effect.

## 18. BOM and material deactivation

Restated for whenever BOM exists (nothing to implement yet): deactivating
a Raw Material must never silently remove it from an existing BOM, nor
rewrite historical BOM/production records. Replacing a deactivated
material in a BOM must be an explicit BOM-side change, never automatic.

## 19. Historical data integrity

Binding on every future consumer: changing a Raw Material's name must
not alter a historical PO description where a transaction snapshot is
required; changing its UoM must not reinterpret a historical quantity;
changing or removing a `SupplierMaterial` relationship must not rewrite
a historical PO; changing `reference_cost` must not alter a historical
purchase price; deactivating a material must not remove a historical
stock movement. Any module that needs to preserve a Raw
Material/SupplierMaterial value at the time of a transaction must
snapshot that value onto its own transaction row — never a live
FK-derived read.

## 20. Organisation scope

Raw Materials are organisation-owned records (`OrganisationScopedMixin`,
same as every other master). `SupplierMaterial` carries no
`organisation_id` of its own — it's a join between two already
org-scoped entities, the same shape as this codebase's own `UserTeam`;
the API layer validates both `supplier_id` and `raw_material_id` belong
to the caller's own organisation on every write. jdk_clean has no
organisation/tenant-scoping concept anywhere (audit #14) — no precedent
to follow, only jdk_erp's own established convention to apply.

## 21. Administration UX

A single flat list page (`DataTable`/`FilterBar`/`FormDialog`/
`ConfirmDialog`/`ActionMenu`/`Badge`), no tabs, no detail route — matching
Category/Unit/Supplier/Product's proportional shape at ~5 records. The
one addition: a "Manage Suppliers" action per row opening a dialog that
lists, adds, edits, and removes that material's `SupplierMaterial`
relationships inline — the one place this module genuinely needs more
than a flat form, since it's a live-managed relationship, not a read-only
summary. A "Used in BOMs" summary panel is still not built here, even
though BOM now exists ([`boms.md`](boms.md)) — that cross-reference
belongs on the BOM screen (which already shows Raw Material per
component), not duplicated as a second read here. "Current Stock" stays
deferred — Inventory doesn't exist yet to source it from.

## 22. Database integrity

`raw_materials`: primary key, `organisation_id` FK (`RESTRICT`, indexed),
`category_id` FK (`RESTRICT`, indexed), `unit_of_measure_id` FK
(`RESTRICT`, indexed), `alternate_conversion_unit_of_measure_id` FK
(`RESTRICT`, indexed, nullable — see §5a), `code`/`name` required,
unique per `(organisation_id, code)` and `(organisation_id, name)`.
`supplier_materials`: primary key, `supplier_id` FK (`CASCADE`, indexed),
`raw_material_id` FK (`CASCADE`, indexed), unique per
`(supplier_id, raw_material_id)` — one relationship row per pair; edit
the existing row rather than creating a duplicate. `reference_cost`,
`purchase_price`, `moq`, `max_supply_quantity`, and `lead_time_days` are
all validated non-negative at the schema layer.

## 23. Referential integrity across the chain

Both chains terminate at the same `raw_materials.id` — there is exactly
one authoritative Raw Material row, referenced by `SupplierMaterial`
today and, once built, by BOM lines, PO lines, receipt records, and
inventory transactions. No module may mint its own material identifier;
every future consumer references this table by foreign key.

## 24. Access and security

Reuses existing RBAC (`require_admin`) exactly like Category/Unit/
Supplier/Product — no Raw-Material-specific authorization layer, and not
jdk_clean's own department-permission-matrix gate for this module (audit
#15), since Raw Material has no ownership dimension. This applies to
`SupplierMaterial` mutations too — managing supplier relationships is a
master-data administration action. Read (`GET /api/raw-materials`,
`GET /api/raw-materials/{id}`, `GET /api/raw-materials/{id}/suppliers`)
is open to any authenticated organisation member; all other mutations
are admin-gated. Organisation isolation and FK validation (category/unit/
supplier must belong to the caller's own organisation) are enforced
server-side on every mutation.

## 25. Performance

No caching layer, no specialised search infrastructure — the expected
volume (~5 rows per organisation, with a handful of supplier
relationships each) doesn't justify it. Listing a material's suppliers
is a single indexed query on `supplier_materials.raw_material_id`, no
N+1 risk at this scale.

## 26. Integration

No consuming module (BOM, Purchase Order, Receipt, Production, Inventory)
exists yet in this codebase. This module establishes the authoritative
material record, plus the Supplier ↔ Raw Material relationship and every
documented historical-integrity/boundary rule above, for those modules
to build against when they land, per Principle 5.

## 27. Acceptance criteria

**Audit**: `jdk_clean` audited — a real, disciplined ~15-field Raw
Material exists with a well-designed (if under-consumed) Supplier
relationship, but Purchase UoM, BOM, Purchase Order, Receipt, and
Inventory infrastructure are either absent or have zero prerequisite in
jdk_erp today (see
[`../audit/RAW_MATERIALS_AUDIT.md`](../audit/RAW_MATERIALS_AUDIT.md));
`jdk_erp` audited — confirmed fully greenfield before implementation.

**Identity**: every Raw Material has one authoritative identity;
code/name unique per organisation; code immutable after creation;
category and unit of measure reference their authoritative masters and
must be active in the caller's own organisation.

**Supplier integration**: `SupplierMaterial` implemented with
supplier-specific code/price/lead-time/MOQ/max-supply-quantity;
zero/one/many suppliers all valid; single-preferred-supplier enforced
service-side; supplier-specific data never duplicated onto Raw Material;
purchase price remains a reference value, never wired into a
non-existent transaction.

**BOM/Procurement/Inventory/Production**: each confirmed to have zero
prerequisite infrastructure in jdk_erp today; each boundary rule
documented above as binding for when that module is built; none built
speculatively now.

**Lifecycle**: active/inactive works; no hard delete; deactivating a
material never touches its `SupplierMaterial` relationships as a side
effect.

**Security**: organisation scope is server-enforced (directly on
`RawMaterial`, transitively via FK validation on `SupplierMaterial`);
RBAC (`require_admin`) is server-enforced; a cross-organisation
category/unit/supplier reference is rejected with 422; a
cross-organisation raw-material id 404s.

**Testing**: create/edit (including the immutable-code case), activate/
deactivate, duplicate code/name rejection (409), invalid/inactive/
cross-organisation category/unit rejection (422), add/list/edit/remove a
supplier relationship, inactive/cross-organisation supplier rejection
(422), duplicate supplier-material pair rejection (409),
single-preferred-supplier enforcement (both on add and on update),
zero-suppliers-is-valid, unauthorized access (401/403), cross-organisation
access (404).

## 28. The structure being built

```text
                    ┌──────────────────┐
                    │   Raw Material   │
                    │                  │
                    │ Code / Name      │
                    │ Category / UoM   │
                    │ Reference Cost   │
                    │ Status           │
                    │ Organisation     │
                    └────────┬─────────┘
                             │
                  ┌──────────┴──────────┐
                  ▼                     ▼
          SupplierMaterial            BOM
        (supplier, price,          (not yet
         lead time, MOQ,            built)
         preferred flag)
                  │
                  ▼
              Supplier
       (Purchase Order / Receipt /
        Inventory -- not yet built)
```

## 29. Most important architectural rule

Raw Material is the authoritative identity connecting procurement and
manufacturing — not merely a list of five materials. Keep the master
lean; make the relationships strong. `SupplierMaterial` is where that
strength lives today; BOM/Purchase Order/Receipt/Inventory each get the
same treatment — an explicit, referentially-intact relationship pointing
at this one authoritative `RawMaterial` row — when they're built, never a
second material representation invented by any of them.

## Implementation approach

Per [`../ENGINEERING_PRINCIPLES.md`](../ENGINEERING_PRINCIPLES.md) §16
("Audit before changing"): see
[`../audit/RAW_MATERIALS_AUDIT.md`](../audit/RAW_MATERIALS_AUDIT.md).
`RawMaterial` structurally mirrors Product's admin-gated CRUD shape
exactly (manual immutable code, required active-and-same-organisation
Category/UoM FKs, one reference-cost field). `SupplierMaterial` is a new
join table shaped like this codebase's own `UserTeam` (no
`organisation_id` of its own, CASCADE on both FKs) carrying the
negotiated terms jdk_clean's real `supplier_materials` table proves are
genuinely useful, minus the columns (`currency`, `onboarded_at`,
`last_transaction_at`) that would have no writer without Purchase
Order/Receipt. `MASTER_DATA_MODULE` (the same shared audit-module
constant every prior Phase 2 entity logs under) is reused again, not a
new module constant.
