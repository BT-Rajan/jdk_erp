# JDK Master Data: Bill of Materials (BOM)

Ninth entity of [`../ROADMAP.md`](../ROADMAP.md) Phase 2 — Master Data,
following Categories, Units of Measure, Customers, Suppliers, Products,
Raw Materials, Machines/Production Lines, and Warehouses. A BOM defines,
for one Product and a specified base quantity of it, exactly how much of
each Raw Material is required to produce that quantity — the single,
unambiguous, enforceable link between finished-goods and raw-material
master data. This is explicitly a **hardening** of a real, working
jdk_clean concept, not a new manufacturing/BOM platform — see
[`../audit/BOMS_AUDIT.md`](../audit/BOMS_AUDIT.md) for the full audit
this module is built from.

## 1. Business model

A BOM header specifies one Product, a base quantity, and (implicitly)
the Product's own unit of measure. Each component line specifies one
Raw Material and how much of it, **in that material's own unit**, is
needed to produce the header's base quantity. Worked example: Product A
(base unit tonne), BOM base quantity 1 tonne, components Material M =
600 kg, Material N = 300 kg (converted from litres), Material P = 100 kg
(converted from bags). A component's quantity is always stored in the
material's own unit — a component whose unit already equals the
Product's own unit needs no conversion at all (ratio 1); this is the
common case, not a special one.

## 2. Product/Material UoM is already explicit

Every `Product` and every `RawMaterial` already carries a required,
FK-validated `unit_of_measure_id` (`docs/modules/products.md`,
`docs/modules/raw_materials.md`) — nothing to add here. A BOM never
assumes a Product's and a Material's units are interchangeable just
because both express a quantity; §5 below is the validation that
enforces this.

## 3. Two separate conversion mechanisms — never one generic engine

Per [`../audit/BOMS_AUDIT.md`](../audit/BOMS_AUDIT.md) §3/§4/§5,
jdk_clean once conflated these into a single column, found it
unworkable, and removed unit conversion entirely rather than fix it.
`jdk_erp` keeps the two cases genuinely separate:

- **Case A — universal conversion** (kg↔g↔tonne, litre↔ml): true
  regardless of what material is being measured.
  `UnitOfMeasure.dimension` (free-form: `"mass"`, `"volume"`, ...) +
  `conversion_factor_to_base` (a ratio within that dimension) — both
  nullable, always both-set-or-both-null (enforced at the API layer,
  including on partial `PATCH` updates, since a request only sees the
  fields it actually sent). A unit with neither (e.g. `"pcs"`) simply
  doesn't participate in universal conversion.
- **Case B — material-specific conversion** (a litre of *this*
  material weighs 1.25 kg; a bag of *this* material weighs 25 kg): a
  property of the specific material (density, packaging), never
  inferable from the unit's name. `RawMaterial.alternate_conversion_
  unit_of_measure_id` + `alternate_conversion_factor` — meaning "1
  [this material's own `unit_of_measure`] = `alternate_conversion_
  factor` [`alternate_conversion_unit_of_measure`]," same both-or-
  neither discipline, plus a same-unit self-reference check (the
  alternate unit must differ from the material's own unit).

`app/services/uom_conversion.py`'s `resolve_conversion_ratio` chains at
most **one** material-specific hop plus **one** further universal hop
(e.g. bag→kg via the material's own factor, then kg→tonne via the
universal dimension) — deliberately not a general multi-hop conversion
graph (§16). If neither mechanism resolves a ratio, the conversion does
not exist — see §5.

## 4. BOM creation rules

A BOM header requires: `product_id` (an active Product in the caller's
own organisation), `base_quantity` (> 0), expressed in the **Product's
own** `unit_of_measure_id` — there is no second, separately-selectable
UoM on the header; storing one would be a second, potentially-diverging
source of truth for a fact `Product` already owns. A component requires
`raw_material_id` (an active Raw Material in the caller's own
organisation) and `quantity` (> 0), expressed in the **Material's own**
`unit_of_measure_id` — never a UoM the caller picks to "make the
numbers work." `product_id` is immutable after creation (sever and
create a new BOM instead of repointing one to a different product);
`raw_material_id` on a component is immutable the same way (remove and
re-add instead of repointing).

## 5. Validate every Product↔Material relationship — the core rule

Before a component can be saved (`POST .../components`), `app/services/
bom_service.require_valid_component_conversion` resolves whether the
material's unit can be related to the product's unit *at all*, via
either mechanism in §3. If no valid conversion exists, the request is
**rejected (422)** with a specific, actionable error — e.g. *"Cannot
establish a valid quantity conversion between Product A (tonne) and
Material N (litre). Configure the required material-specific conversion
on Material N before adding it to this BOM."* — never a silent
assumption that two different units are interchangeable, and never a
silent rounding-away of the problem. The same check re-runs
defensively at activation time (§10), since a unit's dimension or a
material's conversion configuration could change after a component was
originally added.

## 6. Store in the component's native unit

`BomComponent.quantity` is always stored in the Raw Material's own
`unit_of_measure_id` — e.g. `600` (kg), never converted to `0.6`
(tonne) just because the Product happens to be in tonnes. Conversion
(§3) happens only when needed for display (§8) or validation (§5),
computed fresh each time from the stored quantity — never repeatedly
re-converted or cached as a second stored value.

## 7. Production requirement calculation

```text
Required Material = BOM Component Quantity × Requested Production Quantity ÷ BOM Base Quantity
```

Example: BOM base quantity 1 tonne, Material M = 600 kg. A requested
production quantity of 2.5 tonnes ⇒ `600 × 2.5 ÷ 1 = 1500 kg`. This
ratio is dimensionless as long as the requested production quantity is
expressed in the BOM's own base unit (the Product's `unit_of_measure_id`)
— the same assumption jdk_clean's own real `explode_requirements` makes
(`docs/audit/BOMS_AUDIT.md` §7) — so the calculation itself needs no
unit conversion; conversion (§3/§5) only gates *whether a component may
exist on the BOM at all* and drives the display percentage (§8). Each
component's requirement is computed independently, and the result stays
in that component's own unit (`app/services/bom_service.required_
quantity`) — see §11 for who is responsible for using this result.

## 8. Percentage display — derived, never authoritative

A component's percentage share of the BOM (e.g. 600 kg of 1000 kg total
= 60%) is computed at read time only (`app/services/bom_service.
component_percentage`), from the stored quantity converted into the
Product's own unit — it is never stored, and there is no separate field
a caller could edit independently of quantity. Quantity is the one
authoritative value (`BomComponentOut.percentage` is always `None` when
no valid conversion exists — see `conversion_ok`/`conversion_error`
alongside it).

## 9. Preventing ambiguous BOMs

Blocked, at the database or API layer: a Product or Raw Material
without a configured `unit_of_measure_id` (already structurally
impossible — both are required FKs, see §2); zero or negative BOM
`base_quantity` or component `quantity` (schema validation); duplicate
Raw Material components on the same BOM (`UniqueConstraint(bom_id,
raw_material_id)` — hardens jdk_clean's own app-level-only check,
`docs/audit/BOMS_AUDIT.md` §9); a missing/invalid unit conversion (§5);
an inactive or cross-organisation Product/Raw Material reference (422,
same pattern as every other master's FK validation); activating a BOM
with zero components (§10). No business rule beyond these is invented.

## 10. BOM status and versioning

One BOM per Product (`UniqueConstraint(organisation_id, product_id)`,
directly reusing jdk_clean's own real, sound design — `docs/audit/
BOMS_AUDIT.md` §10) — no revision/version history, no ECO workflow;
none is evidenced as needed. Status is `draft`/`active` (renamed from
jdk_clean's `active`/`inactive` for clarity: a not-yet-active BOM here
is "still being built," not "temporarily disabled" the way a Machine or
Warehouse's inactive state means). A `draft` BOM cannot be used to
calculate production requirements (§7/§11 reject with 400 unless
`status == active`). Moving to `active` requires: at least one
component, and every existing component's conversion still resolvable
(§5) — a direct, hardened descendant of jdk_clean's own real `component_
count(...) > 0` activation gate. Moving back to `draft` has no such
gate — a BOM can always be pulled back for editing. No delete endpoint
— deactivate instead, matching every other jdk_erp master.

**Snapshot obligation — binding for a future Production Order module**:
jdk_clean has a real, working `ProductionOrderMaterialRequirement` that
snapshots a calculated requirement onto its own row and explicitly
refuses to recalculate once production execution has started, so that
editing a BOM afterward can never silently corrupt an already-committed
production order (`docs/audit/BOMS_AUDIT.md` §8). `jdk_erp` has no
Production Order table yet (§11) — `POST /api/boms/{id}/calculate-
requirements` is a pure, stateless, always-current calculation with no
memory of a prior answer. **Whichever future Production Order module is
built must snapshot the result it reads from this endpoint onto its own
transaction row, and must protect that snapshot from a later BOM edit
exactly as jdk_clean already does** — this is not optional, and must
not be silently skipped.

## 11. Inventory relationship — responsibilities stay separate

BOM never touches inventory, directly or indirectly. The intended
chain, most of which doesn't exist in `jdk_erp` yet:

```text
BOM (what is required, per unit produced)
  → Production Order (calculates for a specific requested quantity)
  → Inventory (determines what's actually available)
  → Material Allocation (reserves stock against the order)
  → Production Consumption (records actual usage)
```

Only the first step — "what is required" (§7) — is built in this
module, as a stateless calculation. Production Order, Inventory,
Material Allocation, and Consumption are all unbuilt in this codebase;
each is documented above as a binding future consumer of this module's
calculation, never something BOM itself performs.

## 12. UI

A single BOM detail screen per Product: header (Product picker,
Base Production Quantity, its UoM shown read-only from the Product),
and a components table (Raw Material | Required Qty | UoM | Calculated
% | Conversion Status). Conversion internals (which mechanism resolved
a ratio, or why one didn't) are not exposed unless a component actually
has `conversion_ok: false`, in which case the Conversion Status column
shows the same clear, named error §5 raises, with a path to fix it
(configure the material's alternate conversion, or reconsider the
unit). No BOM list beyond "one row per Product with a BOM" is needed
beyond the ordinary master-data list pattern already used everywhere
else (`docs/audit/TABLES_FORMS_MODALS_FILTERS_AUDIT.md`).

## 13. Existing code audit

See [`../audit/BOMS_AUDIT.md`](../audit/BOMS_AUDIT.md) for the full
chain trace (Product→UoM, RawMaterial→UoM, the `units_of_measure.
factor_to_base` experiment and its removal, BOM storage shape,
production requirement scaling, the real Production Order snapshot
precedent, and the activation gate) performed before any implementation
began, per `docs/ENGINEERING_PRINCIPLES.md` §16.

## 14. Test matrix

Covered in `backend/tests/test_uom_conversion.py` (the conversion
service directly) and `backend/tests/test_boms.py` (full API
integration): same-unit component (ratio 1); universal mass conversion
(Product tonne / Material kg); rejection with no valid dimensional
relationship (Product tonne / Material litre, no material-specific
conversion configured); material-specific density conversion (litre →
kg via a configured factor); material-specific packaging conversion
(bag → kg via a configured factor); a component chaining one
material-specific hop plus one further universal hop; zero/negative
base or component quantity rejected; production quantity scaling
(1 tonne / 600 kg → 2.5 tonnes ⇒ 1500 kg, the spec's own worked
example); each component's requirement computed independently and kept
in its own unit; the calculation's stateless, always-current nature
(changing a component after one calculation changes the next one, since
no Production Order exists yet to snapshot against — see §10's binding
note for the future module).

## 15. Database integrity

`boms`: PK; `organisation_id` FK (`RESTRICT`, indexed); `product_id` FK
(`RESTRICT`, indexed); `UniqueConstraint(organisation_id, product_id)`;
`base_quantity` validated strictly positive at the schema layer;
`status` constrained to `draft`/`active` by the schema's validator.
`bom_components`: PK; `bom_id` FK (`CASCADE` — a component cannot
outlive its BOM); `raw_material_id` FK (`RESTRICT`, indexed);
`UniqueConstraint(bom_id, raw_material_id)`; `quantity` validated
strictly positive. `units_of_measure.dimension`/`conversion_factor_to_
base` and `raw_materials.alternate_conversion_unit_of_measure_id`/
`alternate_conversion_factor`: both nullable, both-or-neither enforced
at the API layer (schema-level for `POST`, merged-state check for
`PATCH`), factor validated strictly positive when present.

## 16. Performance

A component's material and unit rows are looked up at most once per
BOM read via a small in-request cache (`app/api/boms.py`'s
`_UnitCache`) — proportionate for a handful of components per BOM, not
a general-purpose data-loading layer. No AI service, no background
job, no generic rules engine, no multi-hop conversion graph (§3) — the
requirement calculation is a single, deterministic pass over a BOM's
components, run synchronously within the request that asks for it.

## 17. Hardening, not a rewrite

Reused directly from jdk_clean (`docs/audit/BOMS_AUDIT.md`): the
one-BOM-per-product model, active-only-counts-for-production, the
activate-requires-≥1-component gate, quantity (never percentage) as the
one stored value, and the `Component Qty × Production Qty ÷ Base Qty`
scaling shape. No second BOM model, no second UoM system, no duplicate
Product/RawMaterial master data, no duplicate inventory logic, no
routing/work-centre concept, and no multi-level/sub-assembly BOM (no
proven need — see the audit §1) are introduced.

## Acceptance criteria

**Audit**: `jdk_clean`'s real, working BOM/UoM/Production-Order-
requirement implementation audited before any code was written (see
[`../audit/BOMS_AUDIT.md`](../audit/BOMS_AUDIT.md)); its one real
conversion mechanism (`factor_to_base`) found to conflate universal and
material-specific facts, built, and removed within nine days — the
central lesson this module is built to avoid repeating.

**Master**: one BOM per Product; header carries `base_quantity` in the
Product's own unit; components carry `quantity` in each Material's own
unit; `product_id`/`raw_material_id` immutable after creation.

**Conversion**: universal (dimension-based) and material-specific
(per-material) conversion are two separate, always-both-or-neither-
configured mechanisms; a component with no valid conversion is rejected
at save time, not silently assumed or rounded away; percentage is
always derived from quantity, never independently stored.

**Calculation**: `Required = Component Qty × Production Qty ÷ Base
Qty`, computed per component, staying in that component's own unit;
stateless — no persisted "production order" of its own; the future
Production Order module's snapshot obligation is documented as binding,
not silently skipped.

**Integrity**: DB-level uniqueness (one BOM per product, no duplicate
components), positive-quantity constraints, and active/same-organisation
FK validation are all server-enforced, not merely UI-enforced.

**Testing**: the full conversion matrix (§14) passes, alongside the
standard CRUD/RBAC/organisation-isolation/audit-trail coverage every
other Phase 2 master already has; all pre-existing tests continue
passing unchanged.

## Most important architectural rule

A BOM answers exactly one question: *for this much of this Product, how
much of each Raw Material is required, and is that requirement even
computable given each side's own unit of measure?* It never decides
whether that material is actually available, never reserves stock, and
never records consumption — those are Inventory, Material Allocation,
and Production Consumption's jobs, none of which exist in this codebase
yet (§11). Keep the relationship (and its conversion validation)
correct and unambiguous; let those future modules build on it rather
than folding their responsibilities into this one.

## Implementation approach

Per [`../ENGINEERING_PRINCIPLES.md`](../ENGINEERING_PRINCIPLES.md) §16
("Audit before changing"): see
[`../audit/BOMS_AUDIT.md`](../audit/BOMS_AUDIT.md). `Bom`/`BomComponent`
mirror jdk_clean's own real header/line split and one-per-product
uniqueness; the conversion mechanism (§3) is built fresh, since
jdk_clean has none left to audit at HEAD (its own attempt was removed);
`MASTER_DATA_MODULE` (the same shared audit-module constant every prior
Phase 2 entity logs under) is reused again, not a new module constant.
