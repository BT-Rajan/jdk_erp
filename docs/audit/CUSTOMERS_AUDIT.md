# Customers Audit — `jdk_clean`

Phase 2 (Master Data) audit of the customer master, per
[`../ROADMAP.md`](../ROADMAP.md) and the spec in
[`../modules/customers.md`](../modules/customers.md). Unlike Categories
and Units of Measure, Customers is a high-volume operational master with
a real ownership/visibility model — this audit is correspondingly
deeper, and drives a genuinely new piece of jdk_erp: the first real
consumer of the OWN/TEAM/ALL permission-scope engine
`docs/modules/permissions.md` already built but never had a caller for.

## Verdict

**Substantial, well-factored prior art on visibility scoping; a bloated
field set to deliberately not reuse.** jdk_clean's `Customer` model
carries ~50 columns — credit terms, GL/bank-account fields, follow-up/
dunning automation, ID verification, a 5-state onboarding-approval
workflow, a purchase-side supplier mirror — the large majority with, by
jdk_clean's own code comments, "no consumer anywhere in this app" (no
posting engine, no automation, manual-only). None of that is reused.
What *is* reused is the shape of the ownership/visibility architecture:
a single nullable `assigned_to` FK, `created_by` deliberately excluded
from visibility, and a consistently-applied scoping layer across every
Sales-adjacent module.

## Field set: deliberately minimal

jdk_clean's full field list (identity, contact, dual address
representations, credit/payment terms, purchase-side mirror, GL stub
fields, follow-up/dunning, ID verification, tags, avatar,
`parent_company_id`) is NOT ported forward. Per this module's own §2
("do not add CRM functionality merely because it could be useful") and
Principle 5 (no abstraction without a real consumer), jdk_erp's
`Customer` carries only: `code` (auto-generated), `name`, `contact_person`,
`phone`, `email`, `address`, `assigned_to_user_id`, `is_active`. Every
excluded field either has no consuming module in jdk_erp yet (credit
limit/payment terms belong to Sales/Finance, which don't exist) or was
already flagged by jdk_clean's own comments as speculative ("stored
only, no posting engine exists"). These can be added later, against a
real requirement, when the module that needs them is actually built.

**`name` is deliberately not deduplicated** — jdk_clean never deduped it
either (only `customer_number`/`code` are DB-unique there). Unlike
Category/Team (internally curated classification labels, correctly
unique per organisation), a customer's name is externally-given
real-world business data; two unrelated real businesses can legitimately
share a name.

**No approval/onboarding workflow is built** — jdk_clean's 5-state
`onboarding_status` exists mainly to gate credit-limit extension, which
has no jdk_erp consumer (no Orders module yet). Per this module's own
§5 ("do not add an approval workflow unless the existing business
actually requires one"), none is built.

**No contacts/addresses child tables** — jdk_clean itself never built
proper one-to-many contact/address tables either; it embedded single
columns on the customer row (plus a separate, undocumented workaround —
individual contacts filed as their own `Customer` rows via
`parent_company_id`, not a real hierarchy). jdk_erp keeps the honest
version of jdk_clean's actual working shape: single embedded
`contact_person`/`phone`/`email`/`address` columns, no
`parent_company_id` workaround.

## Ownership model: reused

jdk_clean's core answer, confirmed in `CustomerCRUD._scope_query`: a
single nullable `assigned_to` FK, not many-to-many. `created_by` is
separate audit history and explicitly **not** consulted for visibility —
reassigning a customer strips the previous salesman's access even though
they created it. jdk_erp reuses this shape exactly (`assigned_to_user_id`),
with one simplification: no separate `created_by` column at all, since
`app/services/audit_service.py`'s `customer_created` event's
`actor_user_id` already records who created a customer, the same way it
does for every other master in this codebase — a second, redundant
column would duplicate that.

## Visibility model: the one deliberate departure

jdk_clean's real, working rule is **department-wide** for a manager
(`department_head`): they see every customer their department's page
access allows, unfiltered by who it's assigned to — not a
reporting-line/hierarchy walk. `users.manager_id` exists in jdk_clean
purely for an org-chart display feature and is explicitly disconnected
from RBAC (confirmed in that model's own comment). jdk_clean has no
working hierarchical-visibility pattern to reuse.

This maps cleanly onto jdk_erp's own, already-established Team concept
(`docs/modules/teams.md` §4: `role = Manager` + `team = Sales` already
means "manages Sales," with no separate hierarchy column) — jdk_erp's
Team is the structural equivalent of jdk_clean's Department. So "manager
sees their team's customers" in jdk_erp is: customers assigned to any
user who shares a team with the manager, resolved via the already-built
`get_user_team_ids()` (`app/services/authorization_service.py`) plus a
join on `user_teams` — not a `manager_id` tree (jdk_erp has no such
column, and per the Teams audit, deliberately never will).

## The permission-scope engine: real, reused, first real consumer

`docs/modules/permissions.md` already built `role_permissions`/
`user_permissions` (with a working `scope` column: `own`/`team`/`all`),
`authorization_service.get_effective_scope()`/`can()`/`get_user_team_ids()`,
and a full admin-gated management API (`app/api/permissions.py`) —
confirmed genuinely working, tested code, not just a designed contract.
What that module's own "Implementation approach" explicitly left
unbuilt: any generic record-level query filter, and the mapping from a
resolved scope to an actual `WHERE` clause against a real table's
`assigned_to`/`team_id` columns — because no module existed yet to need
it. Customers is that first real consumer:
`app/services/customer_scope.py`'s `resolve_view_scope()`/
`visible_customer_filter()`/`can_view_customer()` call the existing
engine directly, adding only the Customer-specific mapping (own =
`assigned_to_user_id == self`; team = `assigned_to_user_id` among
users sharing any of the caller's teams) the engine's own design
anticipated but never wrote.

**Default scope when unconfigured**: `permissions.md` §4 documents a
role-default table (Super Admin/Admin → ALL, Manager → TEAM, Team
Member → OWN) explicitly marked "not a hard-coded absolute rule" — i.e.
a suggested starting point an admin can override per-organisation via
the existing permission API, not something the system enforces
unconditionally. jdk_erp's Customer view-scope resolution applies this
table as a *fallback* only when no explicit `role_permissions`/
`user_permissions` row exists (`customer_scope.py`'s
`_DEFAULT_SCOPE_BY_ROLE`) — an explicit grant, when one exists, always
wins, preserving full admin configurability while making the feature
usable without requiring every organisation to pre-configure it.

## Mutation authorization: `edit` mirrors jdk_clean's real, strict choice

jdk_clean's `build_crud_router` call for customers passes
`strict_write_guard=require_role("admin")` — **create** stays open to
anyone with page-level write access (ordinary sales work), but
**update/delete/restore/activate/deactivate are gated to `role=="admin"`
only** — not even `department_head` (manager) can edit an existing
customer record. jdk_erp mirrors this precisely: `PATCH /api/customers/{id}`
and `PATCH /api/customers/{id}/status` use the same `require_admin`
dependency every other master-data mutation in this codebase already
uses — no new permission-table action needed for edit, since the scope
engine is reserved for the one thing it actually needs to answer
(view-visibility), not layered onto every action speculatively.

**Reassignment is the one narrow, deliberate exception**: jdk_clean gates
`/assign` to `is_admin OR is_department_head` — a team_member can never
reassign, even their own customer. jdk_erp reuses this exact rule as a
plain role check (`_require_can_assign` in `app/api/customers.py`), not
a new scope-table action — a narrow, well-justified business rule
directly adopted from real precedent, not new authorization
infrastructure.

## Duplicate/uniqueness rules

- `code`: DB-unique per organisation, auto-generated
  (`app/core/id_formats.py`'s `CUSTOMER_ID` format, reusing the existing
  prefix+digits utility rather than inventing a parallel one) — never
  client-supplied, mirroring jdk_clean's `customer_number`.
- `phone`: DB-unique per organisation when provided, normalized to
  digits-only **at write time** (`app/schemas/customer.py`'s
  `_normalize_phone`) — a deliberate improvement on jdk_clean's real
  defect: its `_check_duplicate_phone` re-normalized and *scanned every
  existing customer row in Python* on every create/update, an O(n) cost
  the audit itself flags as not scaling. Normalizing once at write time
  makes a plain indexed equality check sufficient instead.
- `name`, `email`: not deduplicated — matches jdk_clean's own real
  behaviour (name was never deduped there either; jdk_clean's `email`
  dedup was app-level only and excluded `alternate_email` — jdk_erp
  carries no `alternate_email` at all, so there's nothing to exempt).

## Downstream references

jdk_clean's own real practice: every downstream table (`quotations`,
`orders`, `deals`, `feasibility_checks`, `payments`) references
`customer_id` as a plain, non-nullable foreign key — **no field-level
snapshotting of customer attributes exists anywhere** in that codebase;
`customer_name` on a quotation/order response is always a live join, not
a stored copy. jdk_erp's Customer master is built the same way: the
authoritative side of a foreign-key relationship for Sales modules
(Feasibility, Quotation, Order, Invoice, Delivery) to reference when
built — none of which exist in jdk_erp yet.

## Known jdk_clean defects, not carried forward

- No `delete_guard` blocking deletion/deactivation of a customer with
  open transactions (unlike jdk_clean's own `departments.py`, which does
  block deleting an in-use department) — worth closing when jdk_erp's
  own Sales modules exist to check against; nothing to check yet today.
- Two independently-editable, unsynchronized address representations
  (free-text `billing_address` vs. structured `address_line1`/`city`/...).
  jdk_erp picks one representation (a single `address` field) instead.
- `code`/tax-identifier duplicate detection relied solely on a DB
  `UNIQUE` constraint with no clean pre-check, unlike phone/email —
  surfacing as a raw `IntegrityError` rather than a friendly message.
  Not applicable to jdk_erp's `code`, since it's server-generated and
  never client-supplied, so a collision is a system's own retry concern,
  not a user-facing validation message (see `_generate_customer_code`'s
  retry loop in `app/api/customers.py`).
