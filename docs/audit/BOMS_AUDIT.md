# Bill of Materials (BOM) — Audit of jdk_clean

Audited before building [`../modules/boms.md`](../modules/boms.md), per
Principle 5 (reuse before creating) and Principle 16 (audit before
changing). Scoped exactly to the user's own spec: a single,
unambiguous, enforceable relationship between a finished Product and
the Raw Materials required to produce a specified base quantity of it —
never a generic multi-level manufacturing/BOM platform. This audit
covers `jdk_clean/backend/app/models/bom.py`, `services/bom_service.py`,
`api/bom.py`, the (added-then-dropped) `units_of_measure` table, and
`services/production_order_material_service.py` (the one real consumer
of a BOM explosion).

## 1. Does jdk_clean have a real, working BOM?

**Yes — a genuinely working, non-trivial one**, not a stub. `Bom`
(header: `bom_number`, `product_id` **unique**, `output_quantity` — the
batch size every line's quantity is expressed against, `status`
(`active`/`inactive`), `notes`) plus `BomLine` (`parent_product_id`,
a **polymorphic** `component_type` ∈ `(raw_material, product)` +
`component_id`, `quantity`, `unit` as a plain `String(20)`,
`scrap_percent`). `bom_service.explode_requirements` recursively walks
multi-level BOMs (a product's own BOM line can be *another product*,
i.e. a sub-assembly), up to `MAX_BOM_DEPTH = 10`, with explicit cycle
detection (`_assert_no_cycle`) before a component can be added.

**Decision: do not carry over multi-level/sub-assembly BOMs.** JDK's
own spec describes a single-level Product→Raw-Material relationship
only; nothing in the spec or this codebase evidences a sub-assembly
need, and adding one now would multiply the conversion-validation
surface (§5 below) well past what's asked. `jdk_erp`'s `BomComponent`
references `RawMaterial` only, never another `Product` — a deliberate,
documented scope cut, not an oversight.

## 2. Product/RawMaterial/UoM chain today

`jdk_erp` already has what jdk_clean's own BOM leans on: `Product` and
`RawMaterial` both carry a required, FK-validated `unit_of_measure_id`
(`UNITS_OF_MEASURE_AUDIT.md`, `RAW_MATERIALS_AUDIT.md`) — "every
Product and every Raw Material must have a clearly defined stock/base
UoM" (spec §2) is **already true** here, nothing to add. jdk_clean, by
contrast, has no such FK at all today (see §3) — its `unit` columns are
bare `ENUM` values with no unit master behind them whatsoever.

## 3. The `units_of_measure` conversion experiment — added, then removed within a week

jdk_clean actually built a real conversion mechanism once:
`migrations/2026-08-26_add_units_of_measure.sql` created a
`units_of_measure` table — `code`, `name`, `category` (`weight` /
`count` / `volume` — a dimension), and **one** `factor_to_base` column
used for *both* universal ratios (`kg`→1, `ton`→1000) *and* a
material-specific packaging assumption in the same column
(`bag` → 50, with the seed data's own comment: *"`bag` = 50kg is a
configurable assumption — edit this row's `factor_to_base` under
Settings → Units of measure if that's wrong for what's actually being
bagged."*). Nine days later, `migrations/2026-09-02_drop_units_of_measure.sql`
removed the table, the FK validation on `raw_materials.unit`/
`bom_lines.unit`, and "the automatic conversion between compatible
units ... in `bom_service.explode_requirements`" **entirely** — its own
comment records the intent plainly: *"there is no more unit conversion
of any kind."*

**This is the single most important precedent for this module.** A
conversion field that conflates a true physical/dimensional ratio
(kg↔ton) with a business-specific packaging or density assumption
(bag↔kg) is exactly the ambiguity the spec's §3 warns against, and
jdk_clean's own history shows it is not merely a theoretical risk — it
was built, found ambiguous/unmaintainable in practice, and removed.

## 4. What jdk_clean settled on instead — and why it isn't reusable

Current `jdk_clean` HEAD has **no unit conversion of any kind**.
`products.unit`/`raw_materials.unit` are fixed `ENUM` picklists —
`RAW_MATERIAL_UNITS = ("kg", "20kg", "25kg", "ton", "ml", "litre", "pcs")`
(`app/models/raw_material.py`), `PRODUCT_UNITS` the same list minus
`pcs` — duplicated a third time as a frontend TS const
(`frontend/src/types/units.ts`) with no single source of truth between
the three. Note **`"20kg"` and `"25kg"` are themselves fake units** —
a specific package size baked directly into the unit name, rather than
a real "bag" unit plus a separate, structured conversion factor. A
`BomLine`'s own `unit` is never client-supplied at all: it is always
**forced** to equal its component's current `unit`
(`_validate_component_exists` → `line["unit"] = ...`), so a BOM line
can never actually hold a different unit than its material — `explode_
requirements` just sums `line.quantity` directly, with **no
conversion, because none is structurally possible.**

This "solves" the ambiguity problem only by making cross-unit BOMs
impossible by construction — which is exactly what this module's spec
forbids (a Product in tonnes and a Material in kg is the spec's own
worked example, and must be *supported*, not sidestepped). **A
half-configured or conflated conversion field is exactly the kind of
ambiguity a BOM component validation must never have to guess about**
— neither jdk_clean's first attempt (§3, one field for two different
kinds of fact) nor its second (§4, no conversion, so no cross-unit BOM
at all) is a safe pattern to copy. `jdk_erp` instead keeps `dimension`+
`conversion_factor_to_base` (universal) and `RawMaterial.alternate_
conversion_*` (material-specific) as two separate, always-both-or-
neither-configured mechanisms — see [`../modules/boms.md`](../modules/boms.md) §3.

## 5. Universal vs. material-specific conversion — real evidence for the two-mechanism split

jdk_clean's own two failed attempts are, between them, direct evidence
for exactly the split the spec asks for: `kg`↔`ton` is a genuine
**universal** ratio (true for any material, §3's `category='weight'`
grouping was the right idea) — that's the "safe half" `jdk_erp` keeps
as `UnitOfMeasure.dimension`/`conversion_factor_to_base`. `bag`↔`kg`
(and later `"20kg"`/`"25kg"` as fake units) is a **material-specific**
fact (a bag of cement and a bag of resin do not weigh the same) that
was wrongly generalized as if it were universal — that's the "unsafe
half," which `jdk_erp` scopes to the one material it's actually true
for via `RawMaterial.alternate_conversion_unit_of_measure_id`/
`alternate_conversion_factor`, never a property of the unit itself. No
half-configured pair is ever allowed to persist (both API layers
enforce both-or-neither, including on partial `PATCH` updates) —
directly closing the exact gap that let jdk_clean's `factor_to_base`
mix the two kinds of fact in the first place.

(Unrelated despite the similar name: jdk_clean also has a
`raw_material_alternatives` table/`raw_material_alternative_service.py`
— an "approved substitute material" concept, e.g. material B may stand
in for material A. That is a completely different feature from unit
conversion and has no bearing on `alternate_conversion_*` here; noted
only to avoid a future reader confusing the two.)

## 6. BOM storage: quantity vs. percentage

jdk_clean stores **quantity only** on `BomLine` (`quantity` + the
component's own `unit`) — there is no percentage column anywhere, and
no UI computes one either. This directly confirms the spec's own §8/§6
instruction: quantity is the one authoritative stored value; a
percentage, if ever shown, must be *derived*, never a second editable
field. `jdk_erp`'s `BomComponent.quantity` (native unit, never
converted at rest) plus `bom_service.component_percentage` (computed
at read time only) follows this precedent exactly — nothing to
reconcile or migrate here, jdk_clean's own design already agrees with
the spec on this point.

`BomLine.scrap_percent` (a real, working wastage allowance, applied in
`explode_requirements`/`explode_requirements_detailed` as `quantity *
(1 + scrap_percent / 100)`) is **found but deliberately not carried
over** — the spec's own formula in §7 (`Required = Component Qty ×
Production Qty ÷ Base Qty`) has no scrap term. This is flagged here
explicitly per the "flag, don't silently migrate" instruction: a real,
working jdk_clean concept, intentionally excluded because it falls
outside what this pass's formula specifies, not overlooked.

## 7. Production requirement scaling — direct precedent for the formula

jdk_clean's `explode_requirements` computes, per BOM level,
`scale = multiplier / bom.output_quantity`, then
`effective_qty = line.quantity * (1 + scrap_percent/100) * scale` —
i.e. **quantity is scaled relative to the header's own batch-size
denominator**, the same shape as this module's `Required Material =
BoM Component Quantity × Requested Production Quantity ÷ BoM Base
Quantity` (spec §7), with jdk_clean's `output_quantity` playing exactly
the role `Bom.base_quantity` plays here. `jdk_erp`'s
`bom_service.required_quantity` is this same ratio, minus the
scrap term (§6) and minus multi-level recursion (§1) — a direct,
narrower descendant of a working, proven calculation, not an invention.

## 8. Snapshot vs. live calculation — the real Production Order precedent

jdk_clean has a genuinely working, persisted answer to "does a
calculated requirement need to survive a later BOM edit," via
`ProductionOrderMaterialRequirement`
(`production_order_material_service.calculate`): a Production Order's
material requirement is **explicitly snapshotted** (delete-then-insert,
idempotent) the first time it's calculated, and `calculate()` **refuses
to recalculate** once production execution has started, with its own
comment stating the reason plainly: *"this production order's
requirement snapshot is now historical."* This is direct, working
evidence that the spec's §11/§10 instruction — "changes to an active
BOM must not silently corrupt already-created production orders" — is
a real, load-bearing rule in this business, not a theoretical concern.

`jdk_erp` has no Production Order table to snapshot onto (Production
Order doesn't exist in this codebase, and the spec's own §11 says BOM,
Production Order, and Inventory are separate responsibilities that
must not be merged — building even a minimal Production Order table
now would be exactly that). `POST /api/boms/{id}/calculate-requirements`
is therefore a **pure, stateless calculation only** — it always reflects
the BOM's current component data, live, with no persistence and no
memory of a prior answer (see `tests/test_boms.py::
test_calculate_requirements_is_stateless_and_reflects_live_bom_state`).
**This is flagged here explicitly, per the "flag, don't silently
migrate" instruction**: jdk_clean's snapshot-on-calculate,
refuse-to-recalculate-after-execution-starts behavior is not
implemented in `jdk_erp` today, and is documented in
[`../modules/boms.md`](../modules/boms.md) §11 as a **binding
requirement** for whichever future Production Order module is built —
it must reuse this exact rule, not invent a different one, and not
skip it.

## 9. Activation gate — direct precedent

jdk_clean's `update_bom_header` already refuses to flip a BOM to
`active` unless its product is active **and** `component_count(...) >
0` (*"Cannot activate an empty BOM — add at least one component
first"*). `jdk_erp`'s `PATCH /api/boms/{id}/status` activation gate —
at least one component, every component's unit conversion still
resolvable — is a direct, hardened descendant of this real rule
(hardened because jdk_clean has no per-component conversion to
re-validate at all, per §4). jdk_clean's own duplicate-component check
(`BomLineCRUD._duplicate_filter`) is **app-level only**; `jdk_erp`
hardens this into a real DB `UniqueConstraint` on `(bom_id,
raw_material_id)` (spec §9's "no orphaned/invalid data" requirement).

## 10. Status model and per-product uniqueness

`boms.product_id` **unique** in jdk_clean (exactly one BOM per product,
no revision/version history) is real, sound, working prior art — the
spec's own §10 explicitly says not to introduce a versioning system
without evidence, and none exists here either. `jdk_erp` keeps this
exact one-per-product model (`uq_boms_organisation_id_product_id`),
renaming jdk_clean's `active`/`inactive` to `draft`/`active` purely for
clarity: a not-yet-activated BOM here is "still being built" (a
`draft`), never "temporarily disabled" the way a Machine or Warehouse's
`inactive` means — BOM has no ongoing operational lifecycle to pause.
No delete endpoint on either side — a BOM is deactivated (moved back to
`draft`), never hard-deleted, matching every other jdk_erp master.

One further RBAC divergence, noted for completeness: jdk_clean gates
**read** access to BOM behind `require_role("admin")` entirely
(`api/bom.py`'s `read_guard`/`write_guard`, both admin-only). `jdk_erp`
opens `GET`/`calculate-requirements` to any authenticated organisation
member and reserves `require_admin` for mutations only — the same
split every other jdk_erp master already uses (Categories, Units,
Products, Raw Materials, Machines, Warehouses), applied here rather
than jdk_clean's stricter, inconsistent-with-the-rest-of-this-codebase
gate.

## Bottom line

jdk_clean has a real, working, multi-level BOM with a real (if
scrap-inflated, multi-level) requirement-explosion service and a real,
working Production Order material-requirement snapshot — genuine prior
art, not a greenfield module. But its one serious attempt at unit
conversion (`units_of_measure.factor_to_base`, conflating a universal
dimensional ratio with a material-specific packaging assumption in one
column) was built and removed within nine days, and what replaced it
(fixed unit `ENUM`s, a BOM line's unit forced equal to its component's
own unit, zero conversion of any kind, fake package-size "units" like
`"20kg"`) sidesteps the cross-unit problem by making it structurally
impossible rather than solving it — not a pattern this module can
safely reuse for its central requirement (Product in tonnes, Material
in kg/litre/bag must all be relatable).

**Reused as-is**: the one-BOM-per-product model, the active-only-
counts-for-production rule, the activate-requires-≥1-component gate,
quantity (never percentage) as the one stored value, and the
`Component Qty × Production Qty ÷ Base Qty` scaling shape.
**Hardened**: the app-level-only duplicate-component check becomes a
DB constraint; the RBAC-read gate is loosened to match every other
jdk_erp master; the missing per-component conversion validation is
added, built from first principles per the spec (§3/§5) rather than
from jdk_clean, which has none to audit.
**Explicitly not carried over, flagged rather than silently dropped**:
multi-level/sub-assembly BOMs (no proven need, out of spec scope),
`scrap_percent` (outside the given formula), the `factor_to_base`
conflated-conversion mechanism (the precise anti-pattern this module
exists to avoid), fake package-size unit names, and the persisted
Production-Order requirement snapshot (no Production Order exists yet
in `jdk_erp` to snapshot onto — documented as a binding rule for
whichever future module builds it, per §8 above).
