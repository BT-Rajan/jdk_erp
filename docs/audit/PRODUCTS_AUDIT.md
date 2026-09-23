# Products — Audit of jdk_clean

Audited before building `docs/modules/products.md`, per Principle 5 (reuse
before creating) and Principle 16 (audit before changing). Scope: does
jdk_clean's Product implementation contain anything worth reusing, and
what does it get wrong? The single most important question, called out
explicitly by the user: the real, distinct relationship between two
lead-time concepts — **Customer Lead Time** (what Sales uses to commit a
delivery date) and **Manufacturing Lead Time** (what a feasibility/
planning workflow uses to assess whether that commitment is achievable).

## 1. Full field list

`backend/app/models/product.py` / `schema.sql:448-498` in jdk_clean:
`code` (unique), `name`, `unit` (ENUM, free-form picklist), `category`
(free-text VARCHAR), `description`, `product_type` (finished_good/
sub_assembly), `selling_price`, `batch_size` + `batch_production_hours`
(how production time is entered), `machine_id` FK, derived
`production_hours_per_unit`, `workers_required`, `status`
(active/inactive), `tags`/`properties` (JSON, explicitly commented "not
read by any business logic"), `reorder_point`/`maximum_stock`
(replenishment thresholds, not live quantities), `inspection_required`,
`qc_notes`, plus timestamp/soft-delete columns.

This is already a fairly disciplined ~20-field model — no variant
builder, no attribute editor, no bundles. Only `tags`/`properties` are
generic-PIM-flavored bloat, confirmed unused by the model's own comments.
**No barcode field and no weight field exist anywhere in jdk_clean.**

## 2. Product code

Manually entered (`ProductCreate.code`, required, `min_length=1`), **not**
auto-generated (unlike `bom_number`/`order_number`, which use a real
number-series service). Unique at the DB level. Immutable after creation
— `ProductUpdate` simply has no `code` field, so there is no update path
for it at all. **Decision for jdk_erp: preserve this exactly.** Unlike
Customer/Supplier, Product's `code` is caller-supplied and required on
create, and absent from the update schema — the spec's own instruction
("do not silently change established business behavior") applies
directly here.

## 3. Category and Unit of Measure

Both free-text/enum in jdk_clean, not FKs — `category` is a plain
VARCHAR explicitly commented "descriptive only... not read by any
business logic"; `unit` is a hardcoded enum. Telling history: jdk_clean
*did* build a real `units_of_measure` master table (migration
2026-08-26) then explicitly reverted it a week later (migration
2026-09-02: "products.unit are ENUM columns... never real foreign keys...
app-level validation only"). This is jdk_clean abandoning its own better
idea, not evidence against FK-ing — jdk_erp already has real Category and
UnitOfMeasure masters from prior modules (`docs/modules/categories.md`,
`docs/modules/units_of_measure.md`). **Decision: Product requires both by
FK**, and — since this is the first real consumer of either master —
enforces they must be *active* at the point of reference, giving
concrete meaning to those modules' own "deactivation only governs new
selection" rule for the first time.

## 4. Customer Lead Time — the critical finding

**This field/concept does not exist anywhere in jdk_clean.** An
exhaustive grep for "lead_time"/"lead time" across the entire repository
returns zero hits. What actually happens instead
(`app/models/order.py`, `services/order_service.py`,
`tests/test_order_delivery_date.py`):

- `Order.requested_delivery_date` is a date Sales enters by hand — no
  formula, no read from Product.
- On confirmation, `confirmed_delivery_date` defaults from
  `requested_delivery_date` only if not already explicitly set.
- After confirmation, changing the delivery date requires a mandatory
  reason and is blocked on draft/delivered/cancelled orders — an explicit,
  audited override, never a silent recompute.
- No stock-availability combination occurs in this path.
- The date is a real column on the transaction row, not a live
  FK-derived value — so no historical-integrity bug here, just no
  lead-time concept at all.

**Conclusion: jdk_clean has no Customer Lead Time field and no
delivery-date-calculation engine.** This is a genuine gap, not prior art
to reuse. Customer Lead Time is designed fresh for jdk_erp, directly from
the user's own description: a simple reference number of days Sales can
consult (and, once Quotation/Order exist, default from and then snapshot
onto the transaction) when committing a date — never a live recomputation
engine.

## 5. Manufacturing Lead Time

Also not a literal field in jdk_clean, but its functional equivalent is
real and consumed: `production_hours_per_unit` + `workers_required` +
`machine_id`, read by `feasibility_service.py`'s `_check_capacity`
(~lines 190-319). It computes a `projected_completion` date by scanning
`production_schedules` for the next vacant machine/worker slot, using
`required_hours = quantity * production_hours_per_unit`, and compares
that against `FeasibilityCheck.required_by_date` (the customer's ask) to
produce a pass/fail with a machine-vs-manpower shortfall reason. This
*is* a real, live capacity-scheduling engine — not decorative — but it is
rate-based (hours/unit → a schedule), never expressed as a simple
"lead time in days" field, and it is consumed only by Feasibility, never
by Order's delivery-date logic directly. **The two concepts are already
architecturally separate in jdk_clean**, just neither is a simple field.

**Decision for jdk_erp**: building jdk_clean's full rate-based capacity/
scheduling engine (batch sizes, machine assignment, worker pools,
production-schedule scanning) right now would be wildly out of scope for
a ~20-product master. Instead, Product carries a simple
`manufacturing_lead_time_days` reference value — exactly matching the
user's own architecture diagram (Product holds the reference value;
Feasibility/Planning, not yet built, is responsible for turning it, plus
stock/material/machine availability, into an actual schedule). When a
real Feasibility module is eventually built, it can consume this field
directly, or supersede it with jdk_clean's richer rate-based model if the
business actually needs that granularity — that decision belongs to that
module's own audit, not this one.

## 6. Selling price vs. transaction pricing

Confirmed correct in jdk_clean: `OrderDetail`/`QuotationDetail` each
store their **own** `unit_price`/`discount_percent`/`line_total`
columns alongside a `product_id` FK — a later `Product.selling_price`
change does not retroactively alter existing quotation/order lines.
`Product.selling_price` is only ever the default pulled in when a new
line is added. **jdk_erp preserves this pattern exactly**: `selling_price`
on Product is a current/default reference value only; any future
Quotation/Order module must snapshot its own price column, never read
Product's live price for a historical record.

## 7. Reference cost

No cost field exists on Product in jdk_clean at all — not
`reference_cost`, not `standard_cost`, nothing. Not decorative-but-unused;
genuinely absent. **Decision: omit it from jdk_erp too** — the spec's own
test is "only if required by the existing business," and there is no
existing business rule to preserve.

## 8. BOM relationship

Clean and one-directional: `boms.product_id` is a unique FK to
`products.id` (at most one BOM per product); `bom_lines.parent_product_id`
FKs to `products.id`, with a polymorphic `component_type`
(raw_material/product) enabling multi-level BOM/sub-assemblies. Explicit
design comment: "Everything about the product itself stays on Product;
this never duplicates it." **Good pattern, nothing to build now** — BOM
doesn't exist in jdk_erp yet; this is the template for whenever it is.

## 9. Inventory boundary

Clean separation: zero on-hand/available/reserved/stock-value columns on
Product. A separate `finished_goods_inventory` table holds actual stock,
keyed by `product_id`. Product only carries *replenishment configuration*
(`reorder_point`/`maximum_stock` — thresholds, not quantities), read by
`inventory_service` to flag low stock against the live inventory row.
**jdk_erp does not add even the threshold pair yet** — the user's own
field list for this module doesn't include them, and Inventory doesn't
exist in jdk_erp yet either; add them when that module is built, per the
same "defer until a real consumer exists" reasoning already applied
elsewhere in this codebase (e.g. Suppliers' deferred Material
relationship).

## 10. Barcode, Product Type, Weight

Barcode and Weight do not exist anywhere in jdk_clean's Product (or
RawMaterial) — nothing to reuse or avoid. `product_type`
(finished_good/sub_assembly) is real and consumed: it's filterable, and
BOM's component polymorphism uses it to let a sub-assembly product be a
component of another product — a genuine, confirmed business distinction,
not invented. **Decision: omit `product_type` from jdk_erp for now
anyway** — its only real consumer is BOM's component polymorphism, and
BOM doesn't exist in this codebase yet. Adding it speculatively ahead of
that consumer would repeat the same mistake Suppliers' audit explicitly
avoided (deferring the Supplier↔Material relationship). Add it when BOM
is built, using jdk_clean's same two-value distinction as the template.

## 11. Lifecycle

`status` enum (active/inactive) plus soft delete (`deleted_at`).
**No delete guard is configured anywhere** — despite Product being
referenced by quotations/orders/BOM/production/inventory in jdk_clean,
nothing blocks soft-deleting a referenced Product; the only safety net is
a read-only `/where-used` panel that informs but doesn't gate. This is a
gap in jdk_clean, not something to reuse. **jdk_erp**: a plain `is_active`
boolean, no hard delete, matching every other master — and no delete
guard is needed yet either, since nothing in jdk_erp references
`products` (BOM/Quotation/Order/Production/Inventory are all unbuilt).
When the first real consumer is built, *that* module is responsible for
respecting `is_active` at selection time, the same rule already
established for Category/Unit/Customer/Supplier.

## 12. Organisation/tenant scoping

None whatsoever in jdk_clean, confirmed again (consistent with every
prior audit) — no `organisation_id`/tenant concept anywhere in
`product.py`, `order.py`, or `quotation.py`. No precedent to follow or
diverge from; Product simply follows jdk_erp's own established
`OrganisationScopedMixin` convention.

## 13. Access and permissions

Department-permission-matrix gate, same pattern audited for Suppliers
(`page_key="products"`, admin always passes). One narrow exception: a
supplier-pricing sub-view is hard admin-only regardless of page
permission — not relevant here since jdk_erp has no Supplier↔Product
relationship (deferred, see the Suppliers audit). **Decision: reuse
Category/Unit/Supplier's plain `require_admin`-gated shape** rather than
jdk_clean's department-permission matrix — Product has no ownership
dimension, so the simpler existing gate is sufficient. Read stays open to
any authenticated organisation member, the same reasoning as every other
master.

## 14. Frontend

Plain react-hook-form + zod pages (`ProductsListPage`, `ProductFormPage`,
`ProductDetailPage`) plus a bulk CSV import/export dialog. No variant
builder, attribute editor, or configurator UI — genuinely proportional to
the ~20-SKU scale already. Nothing to explicitly avoid beyond the
`tags`/`properties` JSON fields, which jdk_erp drops entirely. Bulk
import/export is not built now either — no evidence any current JDK
workflow needs it at ~20 products, and it isn't in the user's field list.

## 15. Downstream consumers

All clean FK references via `product_id`, no denormalization observed:
`OrderDetail`/`QuotationDetail` (FK + own price snapshot), `BomLine`/`Bom`
(FK, no duplication), `FeasibilityLine`, `ProductionSchedule`/
`ProductionOrder`, `finished_goods_inventory`, `delivery_note_lines`,
`product_packaging_lines`. None of these exist in jdk_erp yet — Product
here establishes the authoritative side of every one of these
relationships for those modules to reference by FK when built, per
Principle 5.

## Bottom line

jdk_clean never actually built the Customer-Lead-Time-vs-Manufacturing-
Lead-Time distinction the user described — it has no lead-time fields at
all. Delivery dates are purely manual/negotiated; manufacturing time is a
rate feeding a real capacity-scheduling engine that never touches the
order's delivery date directly. Price snapshotting on transaction lines
is correctly implemented in jdk_clean (no historical-integrity bug to
avoid there) — the same discipline is documented here as a rule for every
future Quotation/Order module to follow. Inventory/BOM/org-scoping
patterns are clean and reusable later; `product_type`, reorder
thresholds, barcode, and weight are all deliberately deferred until a
real consumer (BOM, Inventory, Delivery) exists to need them.
