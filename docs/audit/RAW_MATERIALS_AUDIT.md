# Raw Materials — Audit of jdk_clean

Audited before building `docs/modules/raw_materials.md`, per Principle 5
(reuse before creating) and Principle 16 (audit before changing). Unlike
every prior master, the user was explicit that this one should be "as
detailed as Product, but with the detail concentrated on relationships
rather than generic ERP fields" — Raw Material is the bridge between
Supplier → Purchase Order → Receipt → Inventory on one side, and
BOM → Production on the other. This audit prioritizes the Supplier ↔ Raw
Material relationship (the one piece actually buildable now, since both
sides already exist in jdk_erp) over the master's own field list.

## 1. Full field list

`backend/app/models/raw_material.py` / `schema.sql:323-365` in
jdk_clean. Table `raw_materials`: `code` (unique), `name`, `material_type`
(enum raw_material/packaging/consumable), `category` (free text),
`description`, `properties` (JSON k/v bag), `manufacturer`/
`manufacturer_part_number`, `unit` (enum), `reorder_point`/
`safety_stock`/`maximum_stock`, `storage_location`, `default_supplier_id`
FK, `unit_cost`, `inspection_required`/`certificate_required`, `qc_notes`,
`status` (active/inactive/blocked).

No load-bearing grade/specification column exists — `properties` is
explicitly commented "not read by any business logic," same verdict as
Product's `tags`/`properties`. Materials are distinguished purely by
`code`/`name`, matching the spec's own instruction (#16): two
operationally different materials should be distinct authoritative
records, not variants inside an attribute bag.

## 2. Raw Material code

Manual/client-supplied (`RawMaterialCreate.code`, `min_length=1`), no
generator anywhere. DB-unique. `RawMaterialUpdate` has no `code` field at
all, so it's immutable via the API even without a DB-level guard. Same
pattern as Product — preserved exactly for the same reason (don't
silently change established business behaviour).

## 3. Category and Unit of Measure

Both free-text/enum, not FKs (mirrors Product exactly, including the
same abandoned-real-UoM-table history already documented in
`UNITS_OF_MEASURE_AUDIT.md`/`PRODUCTS_AUDIT.md`). **Decision: required
FKs to jdk_erp's own existing Category/UnitOfMeasure masters**, validated
active and same-organisation on every write — identical treatment to
Product, for the identical reason.

## 4. Purchase Unit of Measure

**Not modeled anywhere in jdk_clean.** Only one `unit` per material; no
purchase-vs-stock distinction, no conversion factor, anywhere in the
codebase — confirmed via the BOM/packaging line comments explicitly
stating "no unit conversion anywhere." This is a genuine gap, not a
pattern to reuse. **Decision: do not build one now.** The spec's own
instruction is explicit — determine whether JDK actually needs this
distinction before building it, and don't build a generic conversion
engine on spec. If a real need surfaces later (e.g. "stocked in KG,
purchased in BAG from Supplier X"), the natural home for it is
`SupplierMaterial` (per-relationship), not `RawMaterial` — a conversion
factor is inherently supplier/packaging-specific, not a property of the
material itself.

## 5. Supplier ↔ Raw Material (`supplier_materials`) — the critical relationship

Full column set, `app/models/supplier_material.py` / `schema.sql:374-403`:
`supplier_id` FK, `raw_material_id` FK, `supplier_material_code` (a real,
supplier-specific SKU distinct from the material's own code),
`purchase_price` + `currency`, `max_supply_quantity` (required, no
default), `lead_time_days`, `moq`, `is_preferred` (bool),
`status` (active/inactive, independent of soft-delete — "a pause vs.
severing"), `onboarded_at` (auto-captured), `last_transaction_at` (set
only by an actual PO receipt), plus soft-delete/audit columns.

Key findings:
- `purchase_price` is a **reference/default** price, not read live into
  PO pricing — confirmed via `purchase_order_service.py`: PO line
  pricing actually defaults from `raw_materials.unit_cost`, never from
  `SupplierMaterial.purchase_price`. This is a real inconsistency in
  jdk_clean (a supplier-specific price exists but isn't wired into PO
  defaulting) — worth noting, not necessarily worth fixing yet, since
  jdk_erp has no Purchase Order module to wire it into either way.
- `is_preferred` is enforced **service-side only** (`_enforce_single_preferred`,
  called after every add/update): silently un-sets every other active
  preferred row for that material rather than rejecting the write. No DB
  constraint. **Decision: reproduce exactly** — same silent-unset
  behaviour, same absence of a DB constraint.
- **No minimum supplier count enforced anywhere** — a material can
  legitimately have zero, one, or many suppliers; the frontend's "No
  suppliers linked to this material yet" is a normal empty state, not an
  error. **Decision: reproduce exactly.**
- `onboarded_at`/`last_transaction_at` are only ever written by an actual
  Purchase Order receipt event. **Decision: omit both** — Purchase
  Order/Receipt don't exist in jdk_erp yet, so these would be dead
  columns with no writer; add them when that module exists to actually
  populate them.
- `currency` defaults to a hardcoded value per-row. **Decision: omit** —
  jdk_erp's `Organisation.currency` is already the one place currency is
  recorded; a redundant per-row currency invents multi-currency support
  with zero evidence it's needed.
- The separate `status` (pause) vs `deleted_at` (sever) distinction is
  **not reproduced** — nothing in jdk_erp yet needs to distinguish
  "paused" from "severed but historically referenced," since no
  transaction table exists yet to reference a severed relationship
  historically. A plain `is_active` covers pausing; severing is a real,
  hard `DELETE`.

## 6. BOM line → Raw Material

Confirmed for the raw-material side specifically (already known from the
Products audit): `bom_lines.component_type` enum (raw_material/product) +
`component_id` — purely application-resolved polymorphism, no real DB FK
on `component_id`. **No prerequisite infrastructure exists in jdk_erp**
(no `boms`/`bom_lines` tables) — deferred entirely, same reasoning
already applied to deferring Product's `product_type`.

## 7. Purchase Order → Raw Material

`purchase_order_lines.raw_material_id` is a real FK. The PO line snapshots
its own `quantity`/`unit_price`/`discount_percent`/`line_total`/
`received_quantity` at order time — never read live from RawMaterial or
SupplierMaterial after creation. jdk_clean gets this right (the same
historical-integrity discipline already confirmed for Product's
OrderDetail/QuotationDetail). **No prerequisite infrastructure exists in
jdk_erp** (no `purchase_orders` tables) — deferred entirely. Documented
here as the binding rule for whenever that module is built: a PO line
must snapshot price/quantity, never live-read RawMaterial or
SupplierMaterial for a historical record.

## 8. Receipt → Raw Material

No separate goods-receipt entity in jdk_clean — receiving directly
updates `purchase_order_lines.received_quantity` and writes a
`stock_movements` row. No QC/inspection field captured at receipt despite
`inspection_required`/`certificate_required` flags existing on
RawMaterial — those flags are **not actually enforced anywhere**, a
confirmed-decorative pair. **No prerequisite infrastructure exists in
jdk_erp** — deferred, with jdk_clean's lightweight shape (no separate
receipt entity, just a stock-movement row) noted as the target design
for later.

## 9. Raw Material Inventory

A dedicated `raw_material_inventory` table (current-quantity snapshot,
`raw_material_id` unique) plus a shared `stock_movements` ledger — both a
materialized snapshot and a full movement history, reconciled by a
service layer. `RawMaterial` itself carries **no quantity field** at all
— only planning thresholds (`reorder_point`/`safety_stock`/
`maximum_stock`). **No prerequisite infrastructure exists in jdk_erp** —
deferred entirely, including the thresholds (same reasoning as Product's
deferred reorder point). jdk_clean's ledger-plus-snapshot shape is noted
as the target design for whenever Inventory is built.

## 10. Production / Material Requirement → Raw Material

`production_order_material_requirements` FKs directly to
`raw_materials.id` (not only transitively via BOM), with
`required_quantity`/`allocated_quantity`/`consumed_quantity` tracked
there — confirmed RawMaterial carries none of those fields.
`available`/`shortage` are computed live from inventory at read time, not
stored anywhere. **No prerequisite infrastructure exists in jdk_erp** —
deferred entirely.

## 11. Reference/standard cost

`raw_materials.unit_cost` is distinct from `supplier_materials.purchase_price`
and is genuinely consumed (default PO line price, feeds inventory
valuation) — not decorative, unlike Product's absent equivalent.
**Decision: include one reference-cost field on RawMaterial** (as a
current/default value only, same discipline as Product's
`selling_price`) — the one commercial field this master carries, since
there's real evidence it's used, unlike Product's reference cost (which
had zero evidence and was correctly omitted).

## 12. Material Type, Manufacturer, Barcode, Weight

`material_type` is explicitly documented as not changing any downstream
behaviour — filter-only. `manufacturer`/`manufacturer_part_number` are
pure display fields with no consumer found. No barcode or weight field
exists on RawMaterial at all in jdk_clean. **Decision: omit all of
these** — no proven business requirement for any of them.

## 13. Lifecycle

`status` enum (active/inactive/blocked) plus soft delete. **No
deactivation/delete guard** checking for existing BOM lines, PO lines,
supplier relationships, or inventory before allowing a status change or
delete — the same "no guard at all" verdict already found for Product.
**Decision**: a plain `is_active` boolean (no third "blocked" state — no
evidence it carries distinct behaviour from inactive), no hard delete.
No guard needed yet either, since nothing in jdk_erp references
`raw_materials` — whichever module becomes the first real consumer is
responsible for respecting `is_active` at selection time.

## 14. Organisation/tenant scoping

None whatsoever, confirmed again (consistent with every prior audit) —
no precedent to follow, only jdk_erp's own established convention to
apply to `RawMaterial`. `SupplierMaterial` itself carries no
`organisation_id` either — it's a join between two already org-scoped
entities (Supplier, RawMaterial), the same shape as this codebase's own
`UserTeam`; the API layer validates both sides belong to the caller's own
organisation.

## 15. Access and permissions

Same department-permission-matrix gate as Products/Suppliers
(`page_key="raw_materials"`). **Decision: reuse the plain
`require_admin`-gated shape** instead, same as every other master with
no ownership dimension — including for `SupplierMaterial` mutations,
which are a master-data administration action, not an operational one.

## 16. Frontend

A tabbed detail page (Overview/Stock control/Procurement/Specification/
Alternatives/Where-used/Quality control/Purchase info/History) — heavier
than justified at ~5 materials. The summary strip is, however, exactly
the read-only relationship-summary pattern the user asked for: on-hand/
available (from Inventory), reorder point, preferred supplier, supplier
count, lowest price, lead time — all computed client-side, never a second
source of truth. **Decision**: build a single flat list page (no tabs, no
detail route) with an inline "Manage Suppliers" action per row — the
Supplier ↔ Raw Material relationship is the one place this module
genuinely needs more than a flat form, since it's a live-managed
relationship (add/edit/remove supplier terms), not a read-only summary.
"Used in BOMs"/"Current Stock" summaries are not built — BOM and
Inventory don't exist yet to source them from, and a placeholder panel
with nothing to show would just be dead UI.

## Bottom line

Raw Material's own field list stays as lean as Category/Unit/Supplier —
identity, Category/UoM FKs, description, one genuinely-used reference
cost field, active/inactive. All the relational depth the user asked for
goes into `SupplierMaterial`, the one relationship both fully specified
by the user and fully buildable today (Supplier and Raw Material both
already exist in jdk_erp): supplier-specific code, price, lead time, MOQ,
max supply quantity, and single-preferred-supplier enforcement,
reproducing jdk_clean's own well-designed shape almost exactly, minus the
columns that would be dead weight without Purchase Order/Receipt to write
them. BOM, Purchase Order, Receipt, and Inventory are all confirmed to
have zero prerequisite infrastructure in jdk_erp today and are
deliberately deferred in full, with jdk_clean's shape for each documented
here as the target design for when those modules are built.
