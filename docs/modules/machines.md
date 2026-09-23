# JDK Master Data: Machines & Production Lines

Seventh entity of [`../ROADMAP.md`](../ROADMAP.md) Phase 2 — Master Data,
following Categories, Units of Measure, Customers, Suppliers, Products,
and Raw Materials. This module is the authoritative configuration of
JDK's physical production resource. JDK currently has 1 machine, 1
production line, and a configured production capacity of approximately 2
tonnes per hour — the master stays intentionally tiny, but production
capacity must be a real, structured, configurable value.

## 1. Purpose

Provide the authoritative configuration of the physical production
resource — what machine and production line JDK has, and at what
configured rate it can produce — without prematurely building a generic
manufacturing-resource-management system. No fleet management, no
multi-line routing, no maintenance scheduling.

## 2. Machine / Production Line definition

Two genuinely separate entities, per the user's own explicit instruction
to distinguish them "even if there is currently only one" — a deliberate
departure from jdk_clean, whose single `machines` table secretly *is*
the production line, UI-labelled "Production Line" while the schema
keeps the internal name "machine," with a hard-coded singleton check
rejecting a second row (see
[`../audit/MACHINES_AUDIT.md`](../audit/MACHINES_AUDIT.md) #1).

A **ProductionLine** is the production flow/resource; a **Machine**
references a ProductionLine by FK. No singleton constraint is enforced —
ordinary admin-gated CRUD already produces "exactly one" today without a
business rule that would need relaxing the moment a second line or
machine is added.

## 3. Core fields

**ProductionLine**: id, code (required, system-generated, immutable
after creation), name (required), active/inactive state, organisation,
timestamps. Nothing else — no line balancing, work centres, or routing.

**Machine**: id, code (required, system-generated, immutable), name
(required), production line (required FK, must be active and in the
caller's own organisation), production capacity (required, structured —
see #4), active/inactive state, organisation, timestamps.

**Code generation** (per explicit user instruction, superseding both
masters' original manually-entered code): ProductionLine/Machine/
Warehouse share a distinct `0000`-prefixed shape from the other Phase 2
masters — `app/core/id_formats.PRODUCTION_LINE_CODE`/`MACHINE_CODE`:
`"00001"`/`"00002"` + one free digit, capping each master at 9 records
(a real, intentional business limit for these small, effectively-fixed-
size masters, surfaced as a 400 rather than an unhandled error if hit).

## 4. Production capacity

The most important operational attribute of this master. Stored as
three structured columns on Machine — never a free-text string, never
hard-coded in application code:

- `capacity_quantity` — the numeric rate (e.g. `2`)
- `capacity_unit_of_measure_id` — a required FK to jdk_erp's own existing
  UnitOfMeasure master (e.g. "Ton"), validated active and same-
  organisation on every write, the same treatment already given to
  Product/RawMaterial's Category/UoM FKs
- `capacity_period_hours` — the time period the quantity is produced in,
  in hours (e.g. `1`)

Together these represent "`capacity_quantity` per `capacity_period_hours`
hours" — e.g. 2 tonnes per 1 hour today, or 2.5 tonnes per 1 hour if the
factory's configuration changes tomorrow, updatable by an authorised user
via a plain `PATCH` with no code change required.

Capacity is a reference/planning value only. It must never be confused
with actual production output:

```text
Configured capacity
    ↓
Feasibility / planning (not yet built)
    ↓
Production schedule (not yet built)
    ↓
Actual production (not yet built)
```

## 5. Capacity and Product relationship

**Decision, backed by audit evidence**: no Machine↔Product rate
relationship is built. jdk_clean's actual design puts the real
throughput rate (`production_hours_per_unit`) entirely on Product, with
Machine reduced to an availability window
(`capacity_hours_per_day`) — meaning jdk_clean's schema is *capable* of a
per-product rate, but the audit found no evidence that JDK's real
current business has different actual rates for different products,
only that the schema technically allows it (see
[`../audit/MACHINES_AUDIT.md`](../audit/MACHINES_AUDIT.md) #3/#4). Per
the user's own explicit instruction — build the Product↔Machine
relationship only if proven necessary, otherwise keep one configuration
at the machine/line level — and because jdk_erp's own Product model
(already built) deliberately carries no rate/hours-per-unit field at
all, capacity is modeled once, structurally, at the Machine level. If
real evidence of per-product rate variance surfaces later (a future
Feasibility/BOM audit finds JDK genuinely produces different products at
different rates), that relationship is added then, against its own
audit — never built speculatively now.

## 6. Production line

A ProductionLine has code/name/status/organisation only. A Machine
references its ProductionLine by FK — for the current factory, one
ProductionLine with one Machine. No line balancing, multiple work
centres, routing networks, operation sequences, alternate production
lines, machine groups, or maintenance scheduling are built — none of
that has a proven JDK requirement.

## 7. Production scheduling relationship

Not built yet — Production Scheduling doesn't exist in this codebase.
Documented as the binding chain for whenever it is: Production Order →
Production Schedule → Machine/Production Line → Configured Capacity.
The Machine master must never carry production order status, scheduled
orders, actual production quantity, actual start/end time, operator
activity, or QC result — all Production Schedule/Production concerns.
jdk_clean's own `production_schedules` shape (one row per batch,
`machine_id` + `product_id` + quantity + date range, booked hours
derived per row) is documented in the audit (#7) as the target design
for when that module is built.

## 8. Feasibility relationship

Not built yet — Feasibility doesn't exist in this codebase. Documented
as the binding chain for whenever it is:

```text
Customer Requirement
        ↓
Product
        ↓
Existing Finished Goods?
        │
        ├── Yes → supply from stock
        │
        └── No → Production required
             ↓
        Required quantity ÷ Configured Machine Capacity
             ↓
        Estimated production time
             ↓
        Feasibility / fulfilment date
```

Machine provides the authoritative configurable capacity value only —
Feasibility must never duplicate it as a second, independently-maintained
number.

## 9. Production time calculation

Documented as the binding target formula for whenever Feasibility is
built, per jdk_clean's own audited discipline (fractional hours used
directly, never rounded to whole hours — see
[`../audit/MACHINES_AUDIT.md`](../audit/MACHINES_AUDIT.md) #5):

```text
estimated_hours = required_quantity × (capacity_period_hours ÷ capacity_quantity)
```

For example: required = 6 tonnes, capacity = 2 tonnes per 1 hour →
estimated production time = 6 × (1 ÷ 2) = 3 hours. **Not implemented in
this module** — Machine only provides the authoritative configured
value; the calculation itself belongs to Feasibility.

## 10. Capacity changes and historical records

No historical snapshotting is built. jdk_clean itself never snapshots
the rate/capacity used for a past feasibility or production decision — a
confirmed live-read-only design (audit #8), not an oversight to fix, and
there is no current transaction table in jdk_erp to protect anyway.
Documented as a binding rule for whichever future module reads this
value: it must snapshot the capacity it used onto its own transaction
row at decision time — a later change to Machine's configured capacity
(e.g. 2 → 2.5 tonnes/hour) must never rewrite a historical feasibility
decision, production schedule, or completed production record. This is
the same discipline already established for Product's price/lead-time
fields and RawMaterial's reference cost/SupplierMaterial's purchase
price.

## 11. Lifecycle

```text
Active
  │
  ▼
Inactive
```

No delete endpoint — Machines and ProductionLines are never
hard-deleted, matching every other master. No delete guard is needed yet
either: nothing in jdk_erp references `machines`/`production_lines`
(Feasibility/Production Scheduling are unbuilt) — unlike jdk_clean, which
has real consumers but still only enforces inactive-machine rejection
going forward, never retroactively (audit #9). Deactivating the only
machine today has no operational effect from this module alone, since
there is no scheduling logic here for it to affect; whichever future
Production module schedules against a machine is responsible for
rejecting an inactive one at scheduling time, so that production cannot
silently proceed against a nonexistent resource.

## 12. Organisation scope

Machine and ProductionLine are organisation-owned records
(`OrganisationScopedMixin`, same as every other master). jdk_clean has no
organisation/tenant-scoping concept anywhere (audit #10) — no precedent
to follow, only jdk_erp's own established convention to apply.

## 13. Administration UX

Extremely simple, matching the ~1-machine/1-line reality — reuses
`DataTable`/`FormDialog`/`ConfirmDialog`/`ActionMenu`/`Badge`, no fleet
dashboard, no telemetry. Two flat list pages (Production Lines,
Machines), the same granularity as every other master. Machine's form
includes a Production Line dropdown (populated from the caller's own
active production lines, reusing `GET /api/production-lines`) and a
Capacity Unit dropdown (reusing `GET /api/units-of-measure`) — the same
pattern Product already uses for Category/UnitOfMeasure. Editing allows
an authorised user to reconfigure production capacity (e.g. 2 → 2.5
tonnes/hour) without any code change.

## 14. Database integrity

`production_lines`: primary key, `organisation_id` FK (`RESTRICT`,
indexed), `code`/`name` required, unique per `(organisation_id, code)`
and `(organisation_id, name)`. `machines`: primary key,
`organisation_id` FK (`RESTRICT`, indexed), `production_line_id` FK
(`RESTRICT`, indexed, not unique — nothing stops two machines sharing a
line later), `capacity_unit_of_measure_id` FK (`RESTRICT`, indexed),
`code`/`name` required and unique per organisation, `capacity_quantity`/
`capacity_period_hours` validated strictly positive at the schema layer.
Capacity is never stored as a free-text string.

## 15. Access and security

Reuses existing RBAC (`require_admin`) exactly like every other master —
no Machine-specific authorization layer, and not jdk_clean's own
department-permission-matrix gate for this module (audit #11), since
neither entity has an ownership dimension. Read is open to any
authenticated organisation member; create/edit/activate-deactivate are
admin-gated. Organisation isolation and FK validation (production line/
capacity unit must be active and belong to the caller's own
organisation) are enforced server-side on every mutation.

## 16. Performance

No caching, no resource-management services, no queues, no scheduling
engines, no real-time telemetry — the expected volume (1 line, 1 machine
per organisation today) doesn't justify any of it. Ordinary indexed
relational queries, the same common list infrastructure every other
master reuses.

## 17. Integration

No consuming module (Feasibility, Production, Production Scheduling)
exists yet in this codebase. This module establishes the authoritative
machine/production-line identity and configured capacity value, plus
every documented boundary/historical-integrity rule above, for those
modules to build against when they land. No downstream module may
maintain its own machine or production-line definition.

## 18. Acceptance criteria

**Audit**: `jdk_clean` audited — it conflates Machine and Production
Line into one singleton-enforced table with an availability-only
capacity field, and puts the real per-product rate on Product instead;
neither pattern is followed (see
[`../audit/MACHINES_AUDIT.md`](../audit/MACHINES_AUDIT.md)); `jdk_erp`
audited — confirmed fully greenfield before implementation. Per-product
capacity requirement ruled out for lack of evidence, not overlooked.

**Master data**: Machine has one authoritative identity; ProductionLine
has one authoritative identity; the Machine→ProductionLine relationship
is a clear, validated FK; active/inactive works on both.

**Capacity**: production capacity is configurable via a plain `PATCH`,
no code change required; stored structurally
(quantity/unit/period), never free text; the current ~2 tonnes/hour
configuration is representable exactly; no capacity value is hard-coded
anywhere in application code.

**Feasibility**: not built yet, but the authoritative capacity value and
the target production-time formula are both documented as the
integration point for whenever it is; no capacity value is duplicated
into a second, independently-maintained number anywhere.

**Production**: not built yet, but the boundary (no order status,
quantities, or timing on Machine) is documented; historical
production/feasibility records, once they exist, must remain valid after
a later capacity change (a binding rule documented for that future
module, since there's nothing yet in this codebase for a change to
retroactively break).

**Security**: organisation scope is server-enforced; RBAC
(`require_admin`) is server-enforced; a cross-organisation or inactive
production-line/capacity-unit reference is rejected with 422; a
cross-organisation machine/production-line id 404s.

**Testing**: create Machine and ProductionLine, link Machine to
ProductionLine, configure capacity (2 tonnes/1 hour), reconfigure
capacity without a code change, duplicate code/name rejection (409),
inactive/cross-organisation production-line or capacity-unit rejection
(422), non-positive capacity rejection (422), immutable code (a `code`
sent on `PATCH` is silently ignored), activate/deactivate, unauthorized
access (401/403), cross-organisation access (404).

## 19. The structure being built

```text
1 Production Line
       ↓
1 Machine
       ↓
Configurable Production Rate
 (capacity_quantity / capacity_unit_of_measure / capacity_period_hours)
       ↓
Feasibility / Planning (not yet built)
       ↓
Production Schedule (not yet built)
       ↓
Actual Production (not yet built)
```

## 20. Most important architectural rule

Keep Machine and Production Line master data simple, but make production
capacity authoritative and configurable. The master answers exactly one
question: *what production resource do we have, and at what configured
rate can it produce?* It must never become a production scheduling
system, a maintenance system, a machine telemetry system, a workforce
management system, or a generic work-centre engine. One machine today
does not justify a fleet-management architecture — but its configurable
production capacity is fundamental to JDK's feasibility and production
flow, so that part is modeled properly: structured, validated, and
changeable without a code deployment.

## Implementation approach

Per [`../ENGINEERING_PRINCIPLES.md`](../ENGINEERING_PRINCIPLES.md) §16
("Audit before changing"): see
[`../audit/MACHINES_AUDIT.md`](../audit/MACHINES_AUDIT.md). `ProductionLine`
mirrors Category's plain admin-gated CRUD shape exactly. `Machine`
mirrors Product's shape — system-generated immutable code, required
active-and-same-organisation FK validation (for both `production_line_id`
and `capacity_unit_of_measure_id`) — plus the one new element this
module introduces: three structured capacity columns instead of a single
scalar, so the configured rate can be changed by an authorised user
without any code deployment. `MASTER_DATA_MODULE` (the same shared
audit-module constant every prior Phase 2 entity logs under) is reused
again, not a new module constant.
