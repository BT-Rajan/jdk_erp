# Procurement: Purchase Orders

First entity of [`../ROADMAP.md`](../ROADMAP.md) Phase 4 — Procurement &
Inventory, following every Phase 2 master (Suppliers, Raw Materials,
Warehouses, ...). Implements the Purchase Flow:
`Supplier -> Purchase Order -> Receipt -> Raw Material Inventory` — the
one reliable way to buy raw materials and receive them into the
authoritative stock ledger. Audited against jdk_clean first
(`../audit/PROCUREMENT_AUDIT.md`), which has a real, working
implementation of this flow, so this module reuses and hardens far more
than it invents.

## 1. Purpose

Exactly this, no more: `Supplier -> Purchase Order -> Approval/Confirmation
-> Receipt -> Raw Material Inventory`. Not a generic procurement platform
— see #20's binding architectural rule.

## 2. Purchase Order header

`po_number` (system-generated, immutable, unique per organisation —
`PURCHASE_ORDER_ID` in `app/core/id_formats.py`, format `PO000001`),
`supplier_id` (FK, an active Supplier in the caller's own organisation,
immutable after creation), `warehouse_id` (FK, an active Warehouse in the
caller's own organisation, immutable after creation — jdk_clean has no
warehouse dimension at all; jdk_erp already has a real `Warehouse`
master, so every PO commits to exactly one destination warehouse up
front, matching JDK's real one-warehouse-today reality without hard-
coding it), `status`, `order_date` (required), `expected_delivery_date`
(optional), `notes` (optional), `cancel_reason` (set only on cancel),
`organisation_id`, `created_at`/`updated_at`. No commercial total fields
stored on the header — `total_amount` is always the sum of line totals,
computed at read time, never a second stored value that could drift.

## 3. Purchase Order lines

Each line: `raw_material_id` (FK, an active Raw Material in the caller's
own organisation, immutable after creation — remove and re-add instead
of repointing, same discipline as `BomComponent.raw_material_id`),
`quantity` (> 0, expressed in the material's own `unit_of_measure_id` —
see #5), `unit_price` (defaults to `RawMaterial.reference_cost` if the
caller omits it; rejected with a clear error if neither is available —
reproduces jdk_clean's own real, evidenced default-from-reference-cost
behaviour, `../audit/PROCUREMENT_AUDIT.md` #3), `line_total`
(server-computed `quantity * unit_price`, stored as a snapshot — never
read live from `RawMaterial` after creation, same historical-integrity
discipline `../audit/RAW_MATERIALS_AUDIT.md` #7 documents as binding),
`received_quantity` (cumulative, starts at 0, only ever written by the
receive action — #8). No `discount_percent` — no evidenced JDK need, and
one fewer commercial field to keep synchronized with `line_total`.

## 4. Lifecycle

```text
draft
  |
  v
confirmed
  |
  v
partially_received / fully_received
```

plus `cancelled`, reachable from `draft`, `confirmed`, or
`partially_received` (never from `fully_received` — a completed PO is
terminal; never from `cancelled` itself). `partially_received`/
`fully_received` are never a direct target of a status-change call — they
are the side effect the receive action (#8) recomputes from line data,
exactly as jdk_clean's own real design already does. Cancelling requires
a non-blank reason, stored in `cancel_reason`. Every transition not in
this table is rejected server-side with a clear error — never a silently
ignored/absorbed status value.

No `sent` status and no approval-threshold/overdue-escalation feature —
both real in jdk_clean, both dropped here as unevidenced for JDK and
explicitly out of scope per the task's own "do not create elaborate
approval workflows unless already required" instruction
(`../audit/PROCUREMENT_AUDIT.md` #6/#7). No per-line cancel — the whole
PO is cancelled instead; a line already partially received keeps its
history intact regardless.

## 5. Quantity and Unit of Measure

**No purchase UoM, no conversion.** A PO line's `quantity` is expressed
directly in the Raw Material's own `unit_of_measure_id` — the exact same
unit `RawMaterialInventory`/`StockMovement` (#9) use. jdk_clean has no
purchase-vs-stock UoM distinction anywhere despite live procurement (a
confirmed gap, not prior art — `../audit/PROCUREMENT_AUDIT.md` #4), and
jdk_erp's own `RawMaterial` model independently already reached the same
decision (`../audit/RAW_MATERIALS_AUDIT.md` #4). This makes the
"PO says 10 Bags, inventory silently receives 10 Kg" ambiguity the task
spec warns against structurally impossible — there is only ever one unit
in play. If JDK's real procurement ever proves a genuine
"stocked-in-KG-purchased-in-BAG" need, the existing
`RawMaterial.alternate_conversion_unit_of_measure_id`/
`alternate_conversion_factor` mechanism built for BOM
(`docs/modules/boms.md` #3) is the one place it would be resolved — never
a second, PO-specific conversion field.

## 6. Editing rules

`draft`: header (`order_date`, `expected_delivery_date`, `notes`) and
lines (add/edit quantity or unit price/remove) are all editable.
`supplier_id`/`warehouse_id` are immutable from creation, even in draft —
sever and create a new PO instead of repointing one (same discipline as
`Bom.product_id`). Once `confirmed` (or beyond): the header and lines are
frozen — no amendment endpoint exists in this slice (no evidenced JDK
amendment process to reproduce; `../audit/PROCUREMENT_AUDIT.md` doesn't
find one either — jdk_clean's own edit guard is also draft-only). The
only thing that changes a confirmed PO's data afterward is a receive call
(cumulative `received_quantity` only) or a cancel (`status`/
`cancel_reason` only) — never a rewrite of `quantity`/`unit_price`/
`line_total`, and never a rewrite of a past receipt.

## 7. Confirming

`draft -> confirmed` requires at least one line (mirrors BOM's own
"cannot activate with zero components" gate, `docs/modules/boms.md` #10)
and is the point past which lines can no longer be edited (#6). No
approval gate (#4).

## 8. Receiving

`POST /api/purchase-orders/{id}/receive`: takes one or more
`{purchase_order_line_id, quantity}` entries, all from the same PO, all
applied in one transaction. No other field is accepted here — no
`received_date`/`notes` input that would go nowhere; the movement's own
`created_at` (`app/models/inventory.py`) already records when the
receipt was recorded, and there is no evidenced need to backdate one or
attach freeform notes to it. For each line: `quantity` must be `> 0` and
must not exceed that line's own remaining quantity
(`ordered - already-received`) — enforced by one atomic conditional
`UPDATE ... WHERE received_quantity + :qty <= quantity` per line (the
same concurrency-safe conditional-write shape
`app/services/job_service.py`'s `claim_pending_jobs` already established
in this codebase, in place of jdk_clean's row-locking, which has no
precedent here — `../audit/PROCUREMENT_AUDIT.md` #10); a zero-rowcount
result means over-receipt and the whole call is rejected before any line
is applied (never a partially-applied receive). Each accepted line then
writes one `StockMovement` (#9) into the same warehouse the PO itself
names (#2) and the PO's `status` is recomputed:
`fully_received` when every line's `received_quantity >= quantity`,
`partially_received` otherwise. Only `confirmed`/`partially_received`
POs can be received — `draft`, `cancelled`, and already-`fully_received`
are all rejected. The whole call (line updates + stock movements + status
recompute) is one database transaction — if any part fails, nothing is
committed (task's own "receipt + inventory movement must be atomic"
requirement).

The UI defaults each line's receive-quantity input to its own remaining
quantity — the common case (receiving everything ordered) needs no typed
input at all, only a confirm.

## 9. Inventory effect — the minimal ledger this slice needs

Two new tables, reused verbatim as the target shape both
`../audit/RAW_MATERIALS_AUDIT.md` #8/#9 and `../audit/WAREHOUSES_AUDIT.md`
already documented, extended with the `warehouse_id` dimension jdk_clean
never had:

- `stock_movements` — an immutable, append-only ledger row per receipt:
  `raw_material_id`, `warehouse_id`, `movement_type` (only `"receipt"`
  exists in this slice — a small, explicitly-validated set, not a fixed
  enum baked into the schema, so a future Issue/Adjustment/Production
  movement type is a Python constant addition, not a migration), signed
  `quantity`, `reference_type`/`reference_id` (`"purchase_order_line"` /
  the line's id — the generic link back to the source document a future
  Production/Sales movement will reuse the same way), `created_by_user_id`,
  `created_at`. No `updated_at` — a movement is a historical fact, never
  edited (task's own "never silently rewrite historical receipts" rule).
- `raw_material_inventory` — the current-quantity snapshot,
  `(raw_material_id, warehouse_id)` unique, `quantity_on_hand`, updated
  by the same atomic conditional `UPDATE` shape as #8 (or inserted, on
  first receipt into that material/warehouse pair, retried against the
  unique constraint under `IntegrityError` exactly like every other
  code-generation loop in this codebase).

The Purchase Order itself never stores or displays a stock quantity of
its own — `received_quantity` on a line is a receiving-progress counter,
not an inventory figure; the only authoritative stock number is
`raw_material_inventory.quantity_on_hand`, written exclusively through
`app/services/inventory_service.py`. This is deliberately **not** the
full Inventory/Stock Ledger module (`../ROADMAP.md` Phase 4's own next
step) — no adjustments, transfers, or a dedicated Inventory list page are
built here; only the minimal, real ledger receiving itself needs to be
correct and auditable.

## 10. Duplicate/invalid receipt protection

Server-enforced (never merely a disabled button): receiving a
`draft`/`cancelled`/`fully_received` PO is rejected (#8); over-receiving
beyond a line's own remaining quantity is rejected (#8's atomic
conditional update); zero/negative quantity is rejected at the schema
layer (`gt=0`); receiving into/against another organisation's PO 404s,
same as every other cross-organisation lookup in this app. Double-
submission of the exact same receive request (e.g. a double-click) is
guarded at the frontend by disabling the Receive control while the
request is in flight — no server-side idempotency key/invoice-number
dedup is built in this slice (jdk_clean has one via `invoice_number`;
dropped here since no `invoice_number` field exists in this slice at all
— `../audit/PROCUREMENT_AUDIT.md` #10 flags this as a deliberate,
lower-rigor choice, not an oversight).

## 11. Supplier and Raw Material selection

Both real FKs into the existing masters (#2/#3) — never free text, never
a Purchase-specific duplicate record. `SupplierMaterial` (already built,
`docs/modules/raw_materials.md` #6/#7) is not a hard requirement for a PO
line to exist, matching jdk_clean's own real behaviour
(`../audit/PROCUREMENT_AUDIT.md` #3) — it's where supplier-specific
price/MOQ/lead-time context can optionally be looked up while building a
PO, never duplicated onto the PO line itself beyond the one price
snapshot (#3).

## 12. Numbering

`PURCHASE_ORDER_ID = IdFormat(prefix="PO", digits=6)` in
`app/core/id_formats.py` (`PO000001`), generated the same way
`_generate_supplier_code`/`_generate_customer_code` already do:
existing-count-in-organisation-plus-one, retried against the unique
constraint under `IntegrityError` (`_MAX_CODE_ATTEMPTS = 5`, the same
constant every other code-generating endpoint already uses) — safe under
concurrent creation, server-side only, never client-supplied, stable
after creation (no PATCH field for it).

## 13. Permissions

Reuses jdk_erp's own already-built `module_key`/`action`/`scope`
permission engine (`docs/modules/permissions.md`,
`app/services/authorization_service.py`) — the first real module to
actually call it, per that document's own "these are re-verified once a
real module exists" note. `module_key="purchase"`, four actions:
`view`, `create`, `confirm` (also covers cancel — both are the same
PO-lifecycle decision), `receive`. Admin/super_admin always bypass
(`ADMIN_ROLES`), the same unconditional exemption every other admin-
gated mutation in this app uses. Everyone else needs an explicit
`role_permissions`/`user_permissions` grant — no grant means deny,
exactly `permissions.md`'s own documented semantics; an organisation's
admin configures who can do what via the existing `/api/permissions`
endpoints, no Purchase-specific access code. **No `OWN`/`TEAM` scope** —
every granted action sees every PO in the organisation; jdk_clean's own
real design has no ownership/assignment dimension on a PO either
(`../audit/PROCUREMENT_AUDIT.md` #11), so building one now would be
speculative.

## 14. Organisation isolation

Every table here (`purchase_orders`, `stock_movements`,
`raw_material_inventory`) is organisation-scoped
(`OrganisationScopedMixin`, or, for `purchase_order_lines`, implied via
its parent `purchase_orders` row — same shape `bom_components` already
uses). `supplier_id`/`raw_material_id`/`warehouse_id` are all validated
active-and-same-organisation on every write, never trusted from the
client. A cross-organisation `purchase_order_id` 404s, same as every
other master/transaction in this app.

## 15. Database integrity

`purchase_orders`: PK; `organisation_id`/`supplier_id`/`warehouse_id` FKs
(`RESTRICT`, indexed); `UniqueConstraint(organisation_id, po_number)`;
`status` constrained to the five valid values at the schema layer.
`purchase_order_lines`: PK; `purchase_order_id` FK (`CASCADE` — a line
cannot outlive its PO); `raw_material_id` FK (`RESTRICT`, indexed);
`quantity`/`unit_price` validated strictly positive; `received_quantity`
constrained `0 <= received_quantity <= quantity` (enforced by #8's atomic
update, never violated even under concurrent receive calls).
`stock_movements`: PK; `organisation_id`/`raw_material_id`/`warehouse_id`
FKs (`RESTRICT`, indexed); `quantity` strictly positive; indexed on
`(reference_type, reference_id)` for the "movements for this PO line"
lookup. `raw_material_inventory`: PK;
`UniqueConstraint(raw_material_id, warehouse_id)`; `quantity_on_hand`
constrained `>= 0`.

## 16. List and find UX

One list page (`DataTable`/`FilterBar`/`ActionMenu`/`Badge`, the same
common components every other module already uses): PO number, supplier,
warehouse, status, order date, outstanding-receipt indicator (derived —
"2 of 3 lines outstanding," never a stored field). Search by PO number/
supplier name; filter by status. Each row's `ActionMenu` exposes exactly
the next valid action for that PO's current status (#20's "no dead
ends") — never a static, context-blind action list.

## 17. Navigation and create flow

A new top-level "Procurement" nav group (sidebar), containing "Purchase
Orders" — `Home -> Procurement -> Purchase Orders` is 2 navigations,
matching the task's own requirement. Creating a PO: one `FormDialog`
(Supplier, Warehouse, Order Date, Expected Delivery Date, Notes) creates
the empty `draft` header, immediately followed by the same "Purchase
Order" Modal used for viewing/managing/receiving (#18) — add lines there,
`Save Draft` is implicit (every add/edit is already persisted), then
`Confirm` from the same modal. No multi-tab wizard, no separate detail
route — reuses `BomsPage.tsx`'s already-proven
list-plus-child-relationship-Modal pattern exactly
(`../audit/PROCUREMENT_AUDIT.md` #13), just generalized to also carry
receiving controls once the PO is past `draft`.

## 18. No dead ends

One Modal per PO (opened from the list row's `ActionMenu`, e.g. "View" /
"Manage Lines...") always shows: header summary, and a line-items table
with Ordered/Received/Remaining columns. Its content adapts to status,
never leaving the user stranded:

- `draft`: Add/Edit/Remove line controls, plus a "Confirm" action once
  ≥1 line exists.
- `confirmed`/`partially_received`: a receive-quantity input per
  outstanding line (defaulted to that line's own remaining quantity),
  a single "Receive" submit, and a "Cancel" action.
- `fully_received`: read-only — Ordered/Received are equal on every
  line, nothing further to do.
- `cancelled`: read-only, with the recorded `cancel_reason` shown.

After a successful receive, the same modal stays open showing the
updated Ordered/Received/Remaining and (if applicable) the new
`fully_received` state — never a bare "success" screen with no next
step.

## 19. Performance

No caching layer, no search engine, no background worker — receiving is
a synchronous request, matching this app's scale (`../ROADMAP.md`
"avoid unnecessary caching layers/queues"). Lookups (`Supplier`,
`RawMaterial`, `Warehouse`) are loaded once per page the same way
`BomsPage.tsx` already loads Products/Raw Materials/Units, not
re-fetched per row. List/detail queries are indexed and paginated the
same way every other module's already are (#15/#16).

## 20. Most important architectural rule

Keep Purchase to exactly `Supplier -> Purchase Order -> Receipt ->
Inventory`. No RFQ/quotation comparison, no vendor scoring beyond the
`SupplierMaterial.is_preferred` flag that already exists, no three-way
matching, no blanket/standing orders, no multi-step requisition-then-PO
approval chain, no budget/cost-center enforcement, no automated
purchasing, no separate GRN document identity. Supplier owns supplier
identity, Raw Material owns material identity, Warehouse owns warehouse
identity — Purchase only ever references them, never duplicates them.
Inventory (the ledger built in #9) owns stock quantity and stock
movement — Purchase causes a movement through receiving, it never
maintains a second, independently-editable stock number of its own.
Production/Sales consuming this stock, and the fuller Inventory module
(adjustments, transfers, low-stock visibility), are explicitly the next
passes, not this one.

## Implementation approach

Per [`../ENGINEERING_PRINCIPLES.md`](../ENGINEERING_PRINCIPLES.md) §16
("Audit before changing"): see
[`../audit/PROCUREMENT_AUDIT.md`](../audit/PROCUREMENT_AUDIT.md). Reuses
jdk_erp's existing `Supplier`/`RawMaterial`/`Warehouse`/`SupplierMaterial`
masters, `IdFormat` code generation, `AppError`/`list_query`/`search`
primitives, `authorization_service`'s permission engine (its first real
caller), and the `BomsPage.tsx` list-plus-Modal frontend pattern —
nothing here is a new architectural shape, only a new module built
against all of it.

## Revision 2 — commercial document workflow

Extends the module above: a PO becomes a controlled commercial document
with an immutable issue/revision history, a distinct supplier-
confirmation event gating receipt, and an official PDF sent through the
existing native email integration. Audited first — see
[`../audit/PROCUREMENT_AUDIT.md`](../audit/PROCUREMENT_AUDIT.md)'s own
Revision 2 section for what already existed to reuse
(`app/services/email_service.py`, the generic `files` table, the
`AuditEvent` history log) versus what was a genuine gap (PDF rendering,
year-scoped numbering).

### 21. Numbering — supersedes #12

`YY5NNNN` — 2-digit year, a fixed `5` (Purchase Order document-type
digit), a 4-digit sequence that resets every calendar year, per
organisation. `purchase_order_service.generate_po_number` — the exact
same shape and mechanism as `rfq_service.generate_rfq_number`
(`docs/modules/rfq.md` #7): count existing POs whose `po_number` starts
with this year's `YY5` prefix, add one, format, retry against the unique
constraint under `IntegrityError`. Replaces the flat `PO000001` scheme
#12 originally specified — not a second numbering mechanism, the RFQ
module's own pattern reused for a second document type.

### 22. RFQ linkage

`PurchaseOrder.rfq_id` (nullable FK) records which RFQ, if any, this PO
was converted from (`docs/modules/rfq.md` #8 already builds the
conversion; this is the column it writes). A PO may still be created
directly with no RFQ — no evidence rules that out, and an emergency/
no-RFQ purchase is a legitimate real case — but converting a `selected`
RFQ is the preferred, no-re-entry path.

### 23. Status model — supersedes #4

```text
draft
  |
  v
issued  <---------.
  |                | ("create revision" -- reopens editing)
  v                |
supplier_confirmed-'
  |
  v
partially_received / fully_received
```

plus `cancelled`, reachable from `draft`, `issued`, `supplier_confirmed`,
or `partially_received`. What used to be a single `confirmed` status
(#4) is now two distinct, honestly-named events, per the task's own
explicit "sent ≠ confirmed ≠ received" rule (#26): **`issued`**
means the formal PO document has been generated and (optionally) sent to
the supplier — it does not mean the supplier accepted it. **`supplier_
confirmed`** means the supplier's acceptance has actually been recorded
(#25) — only this status (or `partially_received`) makes a PO
receivable; `issued` alone does not (closes the exact gap #15/#26 of the
new spec calls out).

`issued -> draft` ("Create Revision") reopens an issued PO for editing
without losing its history — the PO's `revision_number`/`po_number`
never change; the next `draft -> issued` transition snapshots a new
`PurchaseOrderRevision` (#24) at `revision_number + 1`. This is
deliberately *not* a separate "negotiating" status — it's the same
`draft` state every unissued PO starts in, distinguished only by
`revision_number > 0` meaning "this draft has been issued and is now
being renegotiated." No state is added merely because the task's prose
names one (`docs/audit/PROCUREMENT_AUDIT.md` #6's own discipline,
applied again).

### 24. Revisions — immutable issued-document history

Two new tables. `purchase_order_revisions`: one immutable row per
`draft -> issued` transition — `revision_number` (1, 2, 3, ...),
snapshotted `order_date`/`expected_delivery_date`/`notes`/
`supplier_reference`/`payment_terms`/`total_amount`, `issued_at`,
`issued_by_user_id`. `purchase_order_revision_lines`: a snapshotted copy
of every line (`raw_material_id`/`quantity`/`unit_price`/`line_total`)
*as it existed at that issue moment* — never a live reference to the
current (possibly since-edited) `purchase_order_lines` rows. The
generated PDF for that revision (#27) is a `files` row linked to it
(`entity_type="purchase_order_revision"`) — also immutable, never
regenerated from today's data even if the organisation's letterhead
details change later (task's own explicit "never silently regenerate a
historical document" rule, #18). Viewing revision 1 always shows exactly
what was issued as revision 1, whatever the PO's current draft state is.

`purchase_order_lines` (the live table, #3) remains the *current*
editable state — what a new revision would snapshot if issued next, and
what `received_quantity` (#8) is tracked against, since receiving always
applies to the PO's current/confirmed terms, never to one specific
historical revision.

No diff/comparison engine is built (`docs/audit/PROCUREMENT_AUDIT.md`
Revision 2 #4's explicit "keep it simple, rely on immutable history"
instruction) — the frontend shows two revisions' snapshots side by side
using the same table rendering already used elsewhere; a human reads the
numbers, nothing computes or highlights a diff.

### 25. Supplier confirmation

`POST /api/purchase-orders/{id}/confirm-supplier`: `{note?, file_ids?}`.
Only valid from `issued`. Records `supplier_confirmed_at`/
`supplier_confirmed_by_user_id`/`supplier_confirmation_note` on the PO
header (one confirmation event per PO — no evidence a PO is ever
"reconfirmed" after negotiation reopens it, since reopening moves it back
to `draft`, clearing the path to a fresh confirmation once re-issued) and
optionally links already-uploaded evidence files
(`entity_type="purchase_order"`, the same `file_service.attach_files`
call RFQ response capture already established,
`docs/modules/rfq.md` #5/#15) — a signed PO, a confirmation email
screenshot, whatever evidence exists. The supplier is never required to
have an ERP login or account of their own.

### 26. Documents and activity

**Documents**: every file linked to `entity_type="purchase_order"`
(confirmation evidence, ad-hoc supplier documents) or
`entity_type="purchase_order_revision"` (each revision's generated PDF)
for this PO, listed together in issue/upload order — reuses the generic
`files` system exactly as RFQ already does, no new attachment mechanism.
**Activity**: the PO's own `AuditEvent` rows
(`entity_type="purchase_order"`, `entity_id=po.id`), already written by
every mutating endpoint (create/update/line changes/status changes/
receive, plus the new issue/confirm/send actions below) — read via the
existing admin-gated `GET /api/audit-events` endpoint
(`docs/modules/audit_trail.md` #8), never a second, PO-specific history
table. The frontend's Activity panel is therefore admin-only, consistent
with every other audit-trail view in this app.

### 27. PDF generation and sending

`app/services/purchase_order_pdf_service.py` renders a revision's
snapshot (header, supplier block, line-items table, totals, notes) as an
A4 PDF using `reportlab` — the one new dependency this revision adds,
since no PDF-rendering capability exists anywhere in jdk_erp
(`docs/audit/PROCUREMENT_AUDIT.md` Revision 2 #2). The "letterhead" is
the organisation's own already-existing `name`/`address`/`contact_email`/
`contact_phone` fields (`app/models/organisation.py`) — no separate
template/admin entity is built; per the task's own "keep this capability
small, do not build a general-purpose page designer" instruction, reusing
data that already exists is smaller than inventing a place to configure
it a second time. `POST /api/purchase-orders/{id}/send`: only valid once
`issued` (a revision must exist); generates the current revision's PDF if
not already generated, attaches it to the supplier's email
(`app/services/email_service.send_email`, already built and already
attachment-capable — no new email code), and records the outcome as an
`AuditEvent`. A failed send raises before anything is marked sent —
`email_service.send_email` itself raises `BusinessRuleError` on any SMTP/
validation failure, so the API layer's own commit (and thus the "sent"
audit event) is never reached on failure; the PO's own status is
untouched either way (`issued` already covers "a document exists," #23
— sending is a delivery detail, not a status).

### 28. Guard rails — supersedes/extends #10

Receiving is now gated on `supplier_confirmed`/`partially_received`, not
`issued` alone (#23). Issuing requires the PO to be `draft` and have
≥1 line (`docs/modules/purchase_orders.md` #7, unchanged). Confirming
requires `issued`. Sending requires `issued` (a revision must already
exist to send). Every guard remains server-enforced, not merely a
disabled frontend button.

### 29. What stayed unbuilt — explicit deferrals

Per `docs/audit/PROCUREMENT_AUDIT.md` Revision 2's own "no complex
procurement features without an identified business requirement" rule:
no over-receipt tolerance (still hard-blocked, #10 — no audited evidence
JDK's real process allows any approved variance); no PO-level discount/
tax fields (still no evidence, same reasoning #3 already gave); no
separate "communication module" beyond the existing Activity/Documents
panels; no revision-diff/comparison engine (#24). None of these are
oversights — each is the same "decision: defer, no evidence" discipline
this module has used from its first version.

## Revision 3 — supplier payment

Extends the module above: recording money paid to a supplier against a
PO, with history, evidence, and an outstanding-amount calculation — not
a full accounts-payable/finance system (`docs/ROADMAP.md` Phase 7 is
still unbuilt and stays that way). Audited first — see
`docs/audit/PROCUREMENT_AUDIT.md`'s own Revision 3 section.

### 30. Payment model

One new table, `purchase_order_payments`: `payment_number` (system-
generated, `YY7NNNN`, #31), `purchase_order_id` (FK, immutable),
`payment_date`, `amount` (`Numeric(14, 4)`, > 0, never a float — no
monetary column in this codebase ever is), `payment_method` (free text —
no fixed enum, `docs/audit/PROCUREMENT_AUDIT.md` Revision 3 #3's same
reasoning `payment_terms` already established), `reference_number`
(free text — bank ref/cheque number/transaction id), `notes`, `status`
(`recorded`/`cancelled` — #33), `cancelled_at`/`cancelled_by_user_id`/
`cancellation_reason`, `created_by_user_id` (who recorded it, not
necessarily who paid). Only valid against a PO that has actually been
issued (`issued`/`supplier_confirmed`/`partially_received`/
`fully_received` — never `draft`, whose total can still change, and
never `cancelled`).

### 31. Numbering

`YY7NNNN` — the same generator shape used twice already
(`generate_rfq_number`'s `3`, `generate_po_number`'s `5`), extended with
a third fixed digit (`7`) for this document type
(`docs/audit/PROCUREMENT_AUDIT.md` Revision 3 #6).

### 32. Paid / outstanding

`PurchaseOrderOut` gains `paid_amount` (sum of every non-`cancelled`
payment) and `outstanding_amount` (`total_amount - paid_amount`), both
computed at read time — never stored, the same "one authoritative
derivation, never a second drifting value" discipline `total_amount`
itself already established (#2). `total_amount` always reflects the PO's
*current* lines (#2), so a later revision's different total is simply a
different `outstanding_amount` on the next read — no payment row is ever
rewritten because of a revision (`docs/modules/purchase_orders.md`
Revision 3's own "historical payments must remain unchanged" rule); if a
revision changes the total enough to need finance's attention, the
`outstanding_amount` figure itself is that signal, not an invented
automatic refund/credit-note behaviour (none is built).

### 33. Recording and cancelling a payment

`POST /api/purchase-orders/{id}/payments`: `{payment_date, amount,
payment_method?, reference_number?, notes?, file_ids?}`. Rejects a
payment that would push total recorded payments beyond the PO's current
`total_amount` — no overpayment tolerance, no audited evidence permits
one (`docs/audit/PROCUREMENT_AUDIT.md` Revision 3 #5). Evidence files
are linked the same way RFQ responses and PO supplier-confirmation
evidence already are (`entity_type="purchase_order_payment"`,
`file_service.attach_files`). `POST .../payments/{payment_id}/cancel`:
`{reason}` (required) sets `status="cancelled"` — never a hard delete or
a soft-delete-from-view; a cancelled payment stays fully visible in the
PO's payment history with its original amount intact, and no longer
counts toward `paid_amount`.

### 34. Permissions — a genuinely separate grant

`module_key="purchase_payment"`, actions `create`/`cancel` — deliberately
its own module_key, not folded into `purchase`'s existing actions, so an
organisation can grant its Accounts/Finance team the ability to record
and cancel payments *independently* of Procurement's own `purchase`
permissions (create/issue/confirm/receive) — directly the task's own
"a finance person should be able to change payment status" requirement,
achieved entirely through the existing `authorization_service` engine
(its third real module, after `purchase` and `rfq`) with no new access
mechanism. Viewing payments requires no separate permission — they are
part of the PO record `purchase_scope.VIEW` already gates.

### 35. Payment vs. receipt — deliberately independent

Recording or cancelling a payment never touches `stock_movements`/
`raw_material_inventory`, and receiving never reads payment state — the
two are enforced as fully independent transactions
(`docs/audit/PROCUREMENT_AUDIT.md` Revision 3 #4): "receipt complete,
payment outstanding" and "payment complete, receipt pending" are both
valid, ordinary situations, never blocked against each other. No
payment-before-receipt gate is built (#4's own reasoning).

### 36. What stayed unbuilt — explicit deferrals

Per `docs/audit/PROCUREMENT_AUDIT.md` Revision 3's own findings: no
supplier-invoice entity (no evidence one exists to link to, task's own
explicit instruction not to build one here); no payment-before-receipt
enforcement (#35); no overpayment tolerance (#33); no multi-step payment
approval chain ("Pending → Under Review → Finance Approved → ...") —
a payment is `recorded` directly by whoever has the `create` grant, the
same "don't invent a lifecycle with no evidence" discipline this whole
module has used from its first version; no payment-terms enum (#30); no
separate global "Supplier Payments" navigation menu — payments live on
the PO detail Modal exactly where Documents/Activity already do
(#17/#26), reachable in the same 2 navigations as the PO itself.

## Revision 4 — Goods Receipt

Per `docs/audit/PROCUREMENT_AUDIT.md` Revision 4. This is the boundary
between Procurement and physical stock: `RFQ -> PO -> Payment (where
applicable) -> Goods Receipt -> Inventory Ledger`. Only a posted Goods
Receipt moves inventory; RFQ, PO and Payment never do.

### 37. Receipt model — supersedes the old receive-as-action shape

Section #8's original "receiving is an action, not a document" decision
is superseded: a `PurchaseOrderReceipt` (header) + `PurchaseOrderReceiptLine`
(lines) pair now records what physically arrived, the same "immutable
snapshot" family already used for `PurchaseOrderRevision`. The old
`POST /purchase-orders/{id}/receive` single-call action and
`purchase_order_service.receive_lines` are removed outright (Revision 4
audit #13) — not kept alongside the new flow.

A receipt belongs to exactly one PO (`purchase_order_id`) and inherits
that PO's `warehouse_id` — no separate warehouse choice (audit #10, one
real warehouse master exists today). Each `PurchaseOrderReceiptLine`
points at one `purchase_order_line_id` (never an unordered/arbitrary
material — task's own #6) and snapshots `raw_material_id` + the quantity
that arrived, in that line's already-fixed unit — no receipt-line UOM
field exists, so no UOM mismatch is representable (audit #4, the same
"no purchase-UOM field" design PO lines already use).

### 38. Receipt lifecycle

```
draft -> posted -> reversed
  \-> cancelled
```

- **`draft`**: being prepared, zero inventory effect. Lines can be
  added/edited/removed freely, the same "draft is the only editable
  state" discipline every other document in this module already uses.
- **`posted`**: the one-way transition that creates the inventory effect
  — for every line, in one transaction: an atomic conditional `UPDATE`
  increments `purchase_order_lines.received_quantity` (rejecting
  over-receipt exactly as the old guard did, audit #5), a `StockMovement`
  row is inserted referencing the receipt line (audit #6), and the PO's
  status is recomputed to `partially_received`/`fully_received`. The
  transition itself is an atomic `UPDATE ... WHERE status = 'draft'` —
  posting the same receipt twice (double-click, retry, refresh) finds
  zero matching rows the second time and is rejected with no second
  inventory effect (audit #7).
- **`cancelled`**: a `draft` receipt discarded before posting — no
  inventory effect ever existed to undo.
- **`reversed`**: a `posted` receipt corrected after the fact. Requires a
  reason. Creates one negative-quantity `StockMovement` per line
  (`movement_type="receipt_reversal"`) and steps `received_quantity`
  back down by the same atomic-guard mechanism, then recomputes PO
  status. The original receipt and its original line quantities are
  never edited — they stay visible with their original values forever
  (audit #8). There is no quantity-editing UI for a posted receipt; the
  corrected workflow is reverse, then create and post a new receipt with
  the right figures.

### 39. Receipt creation flow — the PO stays the workspace

Entry point is the PO itself (`purchase_scope.RECEIVE`, already the
permission gating the old receive action — no new permission is added).
"Receive Material" on a `supplier_confirmed`/`partially_received` PO
opens a form pre-loaded with every PO line's ordered/already-received/
remaining quantity; the user only types what arrived per line, exactly
the task's own worked example. Creating the receipt (draft) and posting
it are both reachable from the same PO detail Modal — no separate
receipt route, the same "no dead ends" philosophy #18/#26 already
established, extended with a compact Receipts section next to
Revisions/Payments/Documents.

### 40. Numbering

`YY9NNNN` — the fourth use of the same generator shape (RFQ `3`, PO `5`,
Payment `7`), server-generated, unique per organisation, yearly-resetting
(audit #9).

### 41. Documents and traceability

A receipt can carry attached supplier evidence (delivery note, supplier
invoice, packing slip, photograph — reusing the generic `files` system,
`entity_type="purchase_order_receipt"`, the fourth real consumer) and,
once posted, a system-generated A4 PDF via a new
`purchase_order_receipt_pdf_service.py` built to the exact same shape as
`purchase_order_pdf_service.py` (audit #11) — no second letterhead
concept, no generic templating engine.

Every `StockMovement` a posted receipt line writes carries
`reference_type="purchase_order_receipt_line"` /
`reference_id=<receipt line id>`, so a stock quantity is always traceable
`Inventory Entry -> Receipt Line -> Receipt -> PO -> Supplier` (audit #6)
— answering "why is there 600kg more stock?" directly from the ledger,
no separate lookup table.

### 42. Payment and QC — deliberately unbuilt here

No payment-before-receipt gate: `payment_terms` is free text, not a
structured condition to gate on, and the already-established Revision 3
decision (#35) is unchanged — the PO screen shows Paid/Outstanding next
to Ordered/Received/Remaining for a human to read, receipt is never
auto-blocked by payment state (audit #3).

No QC/inspection step, no accepted-vs-rejected quantity split: no
incoming-QC workflow exists anywhere in either codebase to integrate with
— `RawMaterial`'s own `inspection_required`/`certificate_required`/
`qc_notes` fields are confirmed-dead jdk_clean carryovers, never checked
at receipt there either (audit #2). A receipt's quantity is the full
physical receipt, all of it available stock.

### 43. What stayed unbuilt — explicit deferrals

Per the Revision 4 audit's own findings: no over-receipt tolerance (audit
#5, same as the original guard); no partial in-place correction of a
posted receipt's quantities (#38 — reverse-then-recreate instead); no
QC/accepted-rejected split (#42); no payment-before-receipt enforcement
(#42); no bin/rack/location hierarchy or multi-warehouse receipt choice
(audit #10 — one warehouse, inherited from the PO); no generic document-
templating engine (a second narrow PDF service, not a first generic one);
no separate global "Goods Receipts" navigation menu — receipts live on
the PO detail Modal, the same reachable-in-2-navigations discipline
every other PO sub-record already follows.

## Revision 5 — approval flow, purchase UOM, currency, history

Supersedes the earlier `issued` / `supplier_confirmed` / `fully_received`
lifecycle wherever it conflicts.

**Lifecycle**

```text
draft --submit--> pending_approval --approve--> approved --email / mark sent--> sent
  ^                    |                           |                              |
  '----- send back ----'                           '---- Create Revision ---------'   (back to draft, approve again)
sent --receipts--> partially_received --> received        (side effects of posting receipts)
cancelled <- draft / pending_approval / approved / sent / partially_received   (reason required)
```

- `POST .../submit` (`create` permission): needs at least one item,
  expected delivery date, payment terms and currency.
- `POST .../approve` (new `approve` permission): snapshots the immutable
  revision and renders its PDF (UOM, currency, delivery location and
  instructions, RFQ reference, approver).
- `POST .../send` `{email: true|false}`: emails the approved PDF, or
  records it was sent another way. A sent PO can be re-emailed.
- `PATCH .../status` `{status: "draft" | "cancelled"}`: send back, create
  a revision, or cancel.
- The old confirm-supplier step is removed; goods are received against a
  `sent` PO. Payments can be recorded once approved.

**Header**: PO number and PO date are automatic. Supplier, delivery
location (warehouse), expected delivery date (not in the past), payment
terms and currency (default KWD) are required. Optional: supplier
reference, delivery instructions, notes. `rfq_id` / `rfq_response_id`
keep the RFQ → supplier quotation → PO trail; the PO's own items hold the
final agreed quantities and prices.

**Items**: product/material, quantity > 0, purchase UOM (defaults to the
item's unit; any unit that converts to it), unit price (required — no
longer defaulted server-side), line total (computed), optional required-by
date and specification/remarks. `conversion_factor` (1 purchase unit =
factor item units) is fixed on the line; receipts are counted in the
purchase unit and stock is posted in the item's own unit.

**Payment**: `payment_status` (`unpaid` / `partially_paid` / `paid`) is
derived from recorded payments vs the total; each payment stays its own
record (date, amount, method, reference).

**History**: created / approved / sent / cancelled by and at, plus the
audit trail for every change.

Migration `0034_purchase_order_approval_and_units.py` maps existing
statuses (`issued → approved`, `supplier_confirmed → sent`,
`fully_received → received`), fills approval/sent stamps from existing
history, currency from the organisation, and each existing line's unit
from its item (factor 1).
