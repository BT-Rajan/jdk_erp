# Units of Measure Audit — `jdk_clean`

Phase 2 (Master Data) audit of unit-of-measure handling, per
[`../ROADMAP.md`](../ROADMAP.md) and the spec in
[`../modules/units_of_measure.md`](../modules/units_of_measure.md).

## Verdict

**Real, decisive history to learn from -- but nothing to reuse as-is.**
Unlike Categories (jdk_clean never built anything), units of measure in
jdk_clean went through a genuine three-stage evolution: a proper table
with a conversion mechanism → free text → a hardcoded enum with no
conversion at all. The middle and final stages both failed or were
abandoned for concrete, documented reasons. This audit exists mainly to
settle one question definitively: **does JDK need a unit-conversion
engine?** The evidence says no.

## The three stages, in order

**Stage 1 — a proper table with conversion (`2026-08-26_add_units_of_measure.sql`).**
A `units_of_measure` table: `code`, `name`, `category` (`weight`/`count`/`volume`),
`factor_to_base` (a decimal ratio to a per-category base unit), `is_base`,
`status`, soft-delete. Seeded with four rows: `kg` (base, factor 1),
`ton` (factor 1000), `bag` (factor 50 — "Bag (50kg)"), `pcs` (base,
factor 1). The seed's own comment already flags the problem: *"`bag` =
50kg is a configurable assumption -- edit this row's `factor_to_base`...
if that's wrong for what's actually being bagged."* This single field
conflated two fundamentally different kinds of number: a true physical
constant (1 ton is always 1000 kg, everywhere, forever) and a
business-specific packaging convention (how much a "bag" holds varies by
what's being bagged, and is a fact about a *product's packaging*, not
about the unit "bag" itself).

**Stage 2 — removed for free text (`2026-09-02_drop_units_of_measure.sql`),
about a week later.** The table, its validation, and the automatic
`bag → kg` conversion in `bom_service.explode_requirements` were all
removed. `raw_materials.unit`/`bom_lines.unit` were never real foreign
keys to the table (app-level validation only), so removal was clean. From
this point, a BOM line's unit was defined to always mirror its
component's own unit — locked in the UI, no exceptions — eliminating the
need for conversion at the one place it had been used, rather than fixing
the conversion itself.

**Stage 3 — free text fails, replaced by a hardcoded enum
(`2026-09-20_constrain_unit_enum.sql`), about three weeks later.** During
the free-text window, `"kg"` grew `"Kg"`/`"KGS"` siblings with no
relationship enforced between what a packaging line recorded and what its
material actually used (per `raw_material.py`'s own comment). The fix:
`products.unit`/`raw_materials.unit` became real SQLAlchemy/DB `ENUM`
columns — `RAW_MATERIAL_UNITS = ("kg", "20kg", "25kg", "ton", "ml",
"litre", "pcs")`, `PRODUCT_UNITS` the same list minus `pcs`. Notably,
`bag` never returned as a unit — `20kg`/`25kg` bake the package size
directly into the unit string instead of a generic `bag` + a
separate weight fact.

This entire saga played out against a catalog of **5 products, 4 raw
materials, 1 packaging item** (per the enum migration's own comment) —
i.e. at effectively zero data volume, not under real production load.

## Where this leaves the current (post-migration) codebase

- **No unit-conversion mechanism exists anywhere today.** `BomLine.unit`
  and `ProductPackagingLine.unit` are plain `String` columns, but are
  never client-settable — the backend (`bom_service.py`'s
  `_validate_component_exists`, `packaging_service.py`'s equivalent) always
  forces a line's unit to equal its referenced component's own unit, and
  the frontend (`BomEditor.tsx`) renders the field as a disabled,
  read-only `<TextField>`. `bom_service.explode_requirements`'s own
  docstring: *"there's no unit conversion here... if a BOM line's unit
  ever genuinely differs from its material's unit (e.g. old data), this
  silently sums the raw numbers rather than converting -- there is no
  unit master to convert against anymore."*
- The only surviving "conversion"-shaped concept,
  `RawMaterialAlternative.conversion_ratio`, is unrelated: a *material
  substitution potency ratio* ("1.5 units of the alternative per unit of
  the primary"), used in feasibility/production when an approved
  alternative material is used instead of the BOM's stated one. It
  assumes both materials already share a unit — it is not a unit
  conversion.
- Both enums are global (no organisation/tenant concept exists in
  jdk_clean at all, consistent with every prior audit of this codebase).
- Three independent copies of essentially the same short list: the
  Python tuple, the DB `ENUM`, and a hand-mirrored frontend TypeScript
  const (`frontend/src/types/units.ts`) — no single source of truth, no
  API endpoint serves a unit list at all.

## Conclusion: no conversion engine, but a real single-source-of-truth master

The spec's own §5 asks the question directly: does JDK need `1 Ton = 1000
Kg`-style conversion, and is a `Bag → Kg` packaging relationship a
different kind of thing? jdk_clean's history answers both parts. Yes,
those are different kinds of relationships — its own design already
learned that the hard way, by building a mechanism that treated them as
the same number and then removing it. And no, JDK does not need an
automatic conversion engine for either kind today: the one place a
conversion was ever wired in (BOM explosion) was redesigned to not need
it at all, at a catalog size measured in single digits, and nothing since
has reintroduced the need.

**What jdk_erp builds instead**: a genuine `units_of_measure` master
table — fixing jdk_clean's real, admitted problem (no single source of
truth, three duplicated lists) — with no `factor_to_base`, no
`category`, no conversion column of any kind. `code` is required and
normalized to upper-case at the API boundary specifically to prevent the
`"kg"`/`"Kg"`/`"KGS"` drift jdk_clean's free-text period produced. If a
future module (BOM, once it exists) ever needs a line's unit to differ
from its component's own unit, that is a new, deliberate decision to make
at that time with real evidence behind it — not something this module
pre-builds speculatively.

## Scope decision: organisation-scoped

jdk_clean gives no evidence either way (it has no organisation concept at
all, so its global unit list reflects the absence of multi-tenancy, not a
considered "units should be global" design). `jdk_erp` scopes every other
master-data/business table by organisation
(`OrganisationScopedMixin` — Categories, Teams, Users, ...). Absent a
reason to special-case Units of Measure, this module follows the same
convention as every other master-data entity in this codebase, per
Principle 2 (one source of truth) — a global-vs-org-scoped split with no
supporting evidence would itself be an inconsistency this audit has no
grounds to introduce.
