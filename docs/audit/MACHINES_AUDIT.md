# Machines & Production Lines — Audit of jdk_clean

Audited before building `docs/modules/machines.md`, per Principle 5
(reuse before creating) and Principle 16 (audit before changing). The
single most important question, explicitly flagged by the user: **does
production rate vary by Product in jdk_clean's actual design, or is it
one global machine/line rate?** This determines whether a Machine↔Product
rate relationship is needed, or a single configurable rate on the
machine/line itself is sufficient.

## 1. Machine vs Production Line — one entity or two?

jdk_clean has exactly **one** table, `machines`, and it *is* the
"production line" — there is no separate `production_lines` table
anywhere. The model's own docstring is explicit: "A production line --
shown everywhere in the UI as 'Production Line' even though the
model/table/columns keep the shorter internal name 'machine'." Worse,
`MachineCRUD.create` hard-rejects a second row with
`ConflictError("Only one Production Line is supported...")` — a
singleton enforced in code, and the frontend's "New" button only appears
when zero rows exist.

**Decision for jdk_erp: do not follow this conflation.** Machine and
ProductionLine are built as genuinely separate entities (Machine
referencing ProductionLine by FK), matching the user's own explicit
instruction to distinguish them "even if there is currently only one."
No singleton constraint is enforced either — ordinary admin-gated CRUD
already produces "exactly one" today, without a business rule that would
need relaxing the moment JDK adds a second line or machine.

## 2. Full field list — `machines` table

`code`, `name`, `capacity_hours_per_day` (DECIMAL, default 8 — the only
capacity-shaped field), `status` (active/inactive), plus standard
timestamp/soft-delete/audit columns. Four business columns total.

## 3 & 4. Production capacity — structured, and does it vary by Product?

This is the critical finding. Capacity in jdk_clean is **not** a single
structured value anywhere — it is split across two levels:

- **Machine-level**: `capacity_hours_per_day` — an *availability window*
  (how many hours a day the line runs), not a throughput rate. No
  quantity/unit/hour concept on Machine at all.
- **Product-level**: `products.production_hours_per_unit` (DECIMAL) —
  hours to produce one unit of *that specific product*, entered
  indirectly via `batch_size`/`batch_production_hours` and kept in sync
  by `ProductCRUD` (confirmed identical to the earlier Products audit,
  `docs/audit/PRODUCTS_AUDIT.md`: "`production_hours_per_unit` +
  `workers_required` + `machine_id`, read by `feasibility_service.py`'s
  `_check_capacity`").

**Confirmed: rate is entirely a Product attribute in jdk_clean, not a
Machine attribute.** Machine only answers "is there a free slot" (via
`capacity_hours_per_day` and booked hours in `production_schedules`),
never "how fast." There is no Machine-level rate and no Product↔Machine
join table — every product simply carries its own rate directly.

**Decision for jdk_erp**: the audit found jdk_clean's schema is
*capable* of a per-product rate, but found no evidence that JDK's actual
current business has *different real rates for different products* —
only that the schema technically allows it. Per the user's own explicit
instruction ("do not build this relationship unless the existing
business actually has different rates by Product... otherwise keep the
single configuration at the production-line/machine level"), and because
jdk_erp's own Product model (already built, see
`docs/audit/PRODUCTS_AUDIT.md`) deliberately carries **no** rate/hours-
per-unit field at all, capacity is modeled once, structurally, at the
Machine level: `capacity_quantity` + `capacity_unit_of_measure_id`
(reusing jdk_erp's own UnitOfMeasure master) + `capacity_period_hours` —
e.g. "2 tonnes per 1 hour." No Machine↔Product rate relationship is
built. If real evidence of per-product rate variance surfaces later,
that relationship is added then, against its own audit — not built
speculatively now on the strength of jdk_clean's schema capability alone.

## 5. Production time formula

`feasibility_service.py:238`: `required_hours = round(float(quantity) *
float(product.production_hours_per_unit), 4)` — plain multiplication,
rounded to 4 decimal places, fractional hours used directly (never
rounded up/down to whole hours). A day-level scan
(`find_vacant_slot_completion`) then accumulates `daily_capacity -
daily_booked` day by day until the cumulative free hours cross the
required threshold.

**Decision for jdk_erp**: this formula operates on jdk_clean's
hours-per-unit representation, which jdk_erp does not replicate (see
#3/#4). The jdk_erp-shaped equivalent — `estimated_hours =
required_quantity * (capacity_period_hours / capacity_quantity)` — is
documented in the module spec as the target formula for whichever future
Feasibility module is built, preserving jdk_clean's own discipline of
using fractional hours directly rather than inventing a rounding rule
with no evidence behind it. **Not implemented in this module** — Machine
only provides the authoritative configured value; the calculation
belongs to Feasibility, which doesn't exist in jdk_erp yet.

## 6. Feasibility integration flow

`_check_capacity` reads `product.machine_id` /
`production_hours_per_unit` / `workers_required` live at check-run time,
loads the live `Machine` row, computes required hours, sums existing
`production_schedules` bookings per machine per day, and compares a
projected completion date against `required_by_date`. Everything is a
live read — see #8.

## 7. `production_schedules`

Tracks booked hours indirectly: one row per batch (`product_id`,
`machine_id`, `planned_quantity`, `scheduled_start`/`scheduled_end`,
`status`), with booked hours derived per row as
`planned_quantity * production_hours_per_unit`. `machine_id` defaults
from the product's own usual machine but is stored explicitly, allowing
a batch to run on a different machine than the product's default.
**No prerequisite infrastructure exists in jdk_erp** — Production
Scheduling doesn't exist yet; deferred entirely, with this shape noted
as the target design for when it's built.

## 8. Historical integrity for capacity changes

**No snapshotting exists anywhere.** A grep for "snapshot" near
machine/capacity code returns nothing. `_check_capacity` always re-reads
the live `production_hours_per_unit` and `capacity_hours_per_day` at
check time — a feasibility decision already made writes its own
`capacity_ok`/`estimated_ready_date` onto the `feasibility_lines` row
(so that specific past decision's *output* is preserved), but nothing
freezes the *rate/capacity value itself* at decision time; any new
evaluation always uses whatever is currently configured. This is a
confirmed live-read-only design, not an oversight to fix.

**Decision for jdk_erp**: do not build capacity snapshotting now either
— there's no current transaction table to protect (Feasibility/
Production Schedule don't exist), and the spec itself warns against
"unnecessary historical versioning without evidence." Documented as a
binding rule for whichever future module reads this value: it must
snapshot the capacity it used onto its own transaction row, the same
discipline already established for Product's price/lead-times and
RawMaterial's reference cost/SupplierMaterial's purchase price.

## 9. Lifecycle

`active`/`inactive` status, soft delete, no delete guard (nothing blocks
soft-deleting a machine with active batches referencing it).
Deactivation is enforced only going forward — `production_service.py`
and the Production-Order scheduling path both reject scheduling new work
against an inactive machine, but existing `production_schedules` rows
already pointing at it are untouched; a readiness check flags a
deleted/inactive machine on an existing schedule as a review item, not
an automatic cancellation.

**Decision for jdk_erp**: a plain `is_active` boolean on both Machine and
ProductionLine, no hard delete, no delete guard needed yet (nothing
references either table — Feasibility/Production Scheduling are
unbuilt). Deactivating the only machine today has no operational effect
from this module alone, since there is no scheduling logic here to
affect — whichever future Production module schedules against a machine
is responsible for rejecting an inactive one at scheduling time, matching
jdk_clean's own real (correct) enforcement point.

## 10. Organisation/tenant scoping

None whatsoever, confirmed again (consistent with every prior audit) —
no precedent to follow, only jdk_erp's own established
`OrganisationScopedMixin` convention to apply to both Machine and
ProductionLine.

## 11. Access and permissions

Same department-permission-matrix gate as every other jdk_clean master
(`page_key="machines"`). **Decision**: reuse the plain
`require_admin`-gated shape instead, same as every other jdk_erp master
with no ownership dimension. Read is open to any authenticated
organisation member — a future Feasibility/Production consumer (and
anyone checking current capacity) needs to look this up.

## 12. Frontend

Already minimal in jdk_clean, matching the "tiny master" intent: a
single-row list (`MachinesListPage.tsx`, "Add" button hidden once one
row exists) and a plain create/edit form (Code, Name,
`capacity_hours_per_day`, Status). No fleet dashboard, no telemetry, no
maintenance scheduling — nothing to explicitly avoid reintroducing here
(the only bloat risk jdk_clean carries is on Product's own
batch/capacity fields, already excluded from jdk_erp's Product).

## Bottom line

jdk_clean's real design puts rate entirely on Product and reduces
Machine to an availability window plus identity/status — the opposite of
what this module needs to build, since jdk_erp's Product deliberately
carries no rate field and the user explicitly wants configurable capacity
on the Machine/Production-Line master itself, unless proven otherwise by
per-product rate variance (which the audit did not find real evidence
of — only schema capability). jdk_erp therefore builds two genuinely
separate, tiny entities (ProductionLine, Machine), with Machine carrying
one structured capacity configuration
(`capacity_quantity`/`capacity_unit_of_measure_id`/`capacity_period_hours`)
reusing the existing UnitOfMeasure master — no Machine↔Product rate
relationship, no production-time calculation engine, no historical
snapshotting, all deferred to whichever future Feasibility/Production
module actually needs them, per the same "defer until a real consumer
exists" discipline applied throughout this rebuild.
