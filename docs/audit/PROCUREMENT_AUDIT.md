# Procurement (Purchase Orders) — Audit of jdk_clean

Audited before building `docs/modules/purchase_orders.md`, per Principle 5
(reuse before creating) and Principle 16 (audit before changing). Scope:
Purchase Order + Receiving, the first slice of
[`../ROADMAP.md`](../ROADMAP.md) Phase 4 — Procurement & Inventory. Unlike
every prior module, jdk_clean's implementation here is real, working and
substantial (not a stub/gap like Warehouse or BOM's conversion mechanism)
— this audit is about what to keep vs. deliberately trim, not what to
build from nothing.

## 1. Tables/models

`purchase_orders` (`backend/app/models/purchase_order.py:38-83` in
jdk_clean): id, `po_number` (unique), `supplier_id` FK, `order_date`,
`expected_delivery_date`, `status`, commercial totals
(`subtotal_amount`/`discount_percent`/`discount_amount`/`total_amount`),
`notes`, `auto_created` (MRP-drafted), `cancel_reason`, an approval gate
(`approved_at`/`approved_by`), an overdue-delivery escalation
(`admin_review_required`/`admin_reviewed_at`/`admin_reviewed_by`/
`admin_review_notes`), soft delete. `purchase_order_lines` (`:86-109`):
`raw_material_id` FK (never free text), `quantity`, `unit_price`,
`discount_percent`, `line_total` (server-computed), `received_quantity`
(cumulative, lives directly on the line — no separate receipt-line
table), `is_cancelled`/`cancel_reason` (per-line cancel). No
`organisation_id` anywhere in jdk_clean (confirmed single-tenant, zero
hits for `organisation_id`/`tenant_id` across the whole backend) and no
`warehouse` table/FK at all — stock is one flat row per material
(`raw_material_inventory.quantity_on_hand`), no location dimension.

## 2. Supplier selection

Real FK (`purchase_orders.supplier_id -> suppliers.id`), validated
active/not-deleted at write time (`purchase_order_service._validate_supplier`).
Never free text. jdk_erp's own `Supplier` master (`docs/modules/suppliers.md`)
is a direct, already-built match — reused as-is.

## 3. Raw material selection

Real FK (`purchase_order_lines.raw_material_id -> raw_materials.id`),
validated active/not-deleted per line. Never free text. A material
already on one line is excluded from other lines' dropdowns on the
frontend (repeat quantities go on the existing line, not a duplicate
line). jdk_erp's `RawMaterial` master is the direct, already-built match.
`SupplierMaterial` (price/MOQ/lead-time/`is_preferred`) exists in both
codebases but a PO line is **not required** to have a matching
`SupplierMaterial` row in jdk_clean — line price defaults from
`raw_materials.unit_cost` (jdk_erp: `RawMaterial.reference_cost`,
confirmed genuinely consumed for exactly this in
[`RAW_MATERIALS_AUDIT.md`](RAW_MATERIALS_AUDIT.md) #11), freely editable.
**Decision: reuse this default-from-reference-cost behaviour exactly.**

## 4. Quantities and UoM

**No purchase-vs-stock UoM split exists in jdk_clean at all**, and the
codebase's own history is an explicit lesson against building one:
`RawMaterial.unit` is a single small fixed enum: PO line quantity and
`raw_material_inventory.quantity_on_hand` are always expressed in that
same one unit, no conversion factor, no second UoM field anywhere. A
code comment there records that jdk_clean *used to have* a real
units-of-measure table and free-text units and deliberately moved away
from both after "kg"/"Kg"/"KGS"-style drift with no enforced
relationship — the same lesson `docs/audit/UNITS_OF_MEASURE_AUDIT.md`
and `docs/audit/BOMS_AUDIT.md` already document from this codebase's own
angle. jdk_erp's `RawMaterial` model already independently reached the
identical decision (`RAW_MATERIALS_AUDIT.md` #4: "do not build [a
purchase UoM] now... a genuine gap, not a pattern to reuse"). **Decision:
a Purchase Order line's quantity is expressed directly in the Raw
Material's own `unit_of_measure_id` — no separate purchase UoM, no
conversion engine, no ambiguity possible.** If a real "stocked in KG,
purchased in BAG" need is ever proven, `RawMaterial.alternate_conversion_*`
(built for BOM, `docs/modules/boms.md` #3) is already the one mechanism
this codebase uses for a material-specific unit relationship — reused,
never duplicated with a second conversion field.

## 5. Numbering

Server-generated, atomic, sequential:
`number_series_service.next_number` (`SELECT ... FOR UPDATE` on a
per-doc-type counter row, then `UPDATE ... SET next_number = next_number + 1`)
→ format `PO-00001`. Real, sound design, but jdk_erp has no
`number_series` table and does not use row-locking anywhere in its own
code — its own established pattern for every transactional/master code
(`Customer`/`Supplier`: existing-count-plus-one, retried against the
unique constraint under `IntegrityError`) is simpler and already proven
at this app's scale. **Decision: reuse jdk_erp's own existing code-
generation pattern**, not jdk_clean's `number_series` table — same
per-organisation count-plus-one, same retry-on-`IntegrityError` loop
already used by `_generate_supplier_code`/`_generate_customer_code`.
Format: `app/core/id_formats.py`'s existing `IdFormat` primitive, a new
`PURCHASE_ORDER_ID = IdFormat(prefix="PO", digits=6)` (`PO000001`) — the
same shape family as the existing `QUOTATION_ID`/`ORDER_ID` transactional-
document codes, not the Phase-2-master numeric-prefix shape.

## 6. Status lifecycle

`draft -> sent -> confirmed -> partially_received/received -> (terminal)`,
plus `cancelled` reachable from every non-terminal state, enforced by a
shared `ALLOWED_TRANSITIONS` map + `assert_transition_allowed` helper
(service-layer, not merely a status column). `partially_received`/
`received` are never set directly by a status-change call — they're a
side effect the receiving action recomputes from line data. Per-line
cancel exists alongside whole-PO cancel. Cancelling always requires a
non-blank reason.

**Decision: trim to jdk_erp's own explicit lifecycle**
(`docs/modules/purchase_orders.md` #4) — `draft -> confirmed ->
partially_received/fully_received`, `cancelled` terminal-reachable from
`draft`/`confirmed`/`partially_received`. `sent` is dropped: no evidence
JDK's real process needs a distinct "sent to supplier, not yet confirmed"
state, and the task's own spec lists exactly `Draft -> Confirmed ->
Receive -> Stock Updated`. `received`/`partially_received` stay
side-effects of receiving, never a direct status-change target — this
part of jdk_clean's design is exactly right and is kept. Whole-PO cancel
requires a non-blank reason (kept — cheap, real audit value). **Per-line
cancel is dropped** — the spec's own lifecycle has no such stage, and it
adds a second cancellation surface with no proven JDK need; a line that
shouldn't be delivered is left at its already-partial receipt and the
whole PO is cancelled once nothing further is expected, or a fresh PO is
raised for what's still needed.

## 7. Approval

Real, but narrow: an optional org-wide (or per-supplier override) large-
PO/large-discount KWD threshold, checked only at the `draft -> sent`
transition, single admin sign-off (`approved_at`/`approved_by`), no
approval chain. A second, unrelated "admin review" flag escalates any PO
overdue past its expected delivery date with nothing received yet (a
supplier-running-late flag, not an order-approval step).

**Decision: build neither for this slice.** The task's own instruction is
explicit — "do not create elaborate approval workflows unless they
already exist or are explicitly required" — and neither JDK's own
required lifecycle (task spec) nor this audit's mandate asks for one.
Both are real jdk_clean behaviour, documented here as the target design
if JDK's real process later proves a threshold-approval or overdue-
escalation requirement — not silently lost, deliberately deferred.

## 8. Receiving

No separate GRN/goods-receipt entity — receiving is an *action*
(`purchase_order_service.receive_lines`) that (a) increments
`purchase_order_lines.received_quantity`, (b) inserts one `StockMovement`
row per line, (c) recomputes PO status — all in one transaction. Partial
receipt fully supported across any number of separate calls. Explicit,
deliberate code comments explain *why* a separate receipt document was
avoided. **Decision: reuse this shape exactly** — it is the one part of
this audit flagged as a considered, well-reasoned simplicity choice, not
an oversight (see #13). No separate `purchase_receipts` table.

## 9. Stock effect

Every receipt writes a `StockMovement` (item/material, quantity,
`reference_type`/`reference_id` back to the source document, cost/batch/
etc.) and updates a flat `raw_material_inventory.quantity_on_hand` — the
authoritative ledger-plus-snapshot shape `RAW_MATERIALS_AUDIT.md` #8/#9
and `WAREHOUSES_AUDIT.md` already flagged as the target design once
Inventory exists. **Decision: build the minimal version of this now** —
`stock_movements` + `raw_material_inventory`, extended with the
`warehouse_id` dimension jdk_clean never had (jdk_erp already has a real
`Warehouse` master; jdk_clean never did) — as the smallest authoritative
ledger the Purchase Flow's receiving step needs, not a full Inventory
module (no adjustments, transfers, or a dedicated Inventory list/UI in
this slice — `docs/ROADMAP.md`'s own next-pass note).

## 10. Guard rails

All real, service-layer, explicit (not merely a status column):
wrong-status receipt rejected; over-receiving rejected (validated for the
*whole batch* before any line is applied); zero/negative quantity
rejected at the schema layer; cancelled-line receipt rejected;
duplicate-submission guarded via an `invoice_number` dedup check against
existing `StockMovement` rows; concurrency via row-locking
(`with_for_update`) on both the PO and each line. **Decision**: reuse
every guard except the last two verbatim. Row-locking is dropped — jdk_erp
has no precedent for it anywhere (its one comparable case,
`job_service.claim_pending_jobs`, explicitly chose a conditional
`UPDATE ... WHERE` for portability across SQLite/MySQL over row-locking)
— receiving instead uses the same atomic-conditional-`UPDATE` shape:
`received_quantity`'s increment and its own "cannot exceed ordered
quantity" bound are enforced in one `UPDATE ... WHERE received_quantity +
:qty <= quantity` statement, a zero-rowcount result meaning "over-receipt,
reject" with no read-then-write race. The `invoice_number` dedup guard is
also dropped — no `invoice_number` field is carried in this slice at all
(no evidence JDK's process requires one); double-submission is guarded by
disabling the Receive control while a request is in flight
(ordinary frontend discipline), not a second server-side field with no
other evidenced use. Flagged here as a deliberate, lower-rigor choice,
not an oversight.

## 11. Permissions

Page-level department read/write matrix (`page_key="purchase_orders"`),
admin bypasses everything, `viewer` always read-only, no finer action
granularity (confirm/receive get no separate gate from create/edit), no
ownership/assignment dimension on a PO at all.

**Decision: do not reuse jdk_clean's page-matrix model — use jdk_erp's
own already-built, more capable `module_key`/`action`/`scope` permission
engine** (`docs/modules/permissions.md`, `app/services/authorization_service.py`),
which is documented as awaiting exactly this kind of first real
transactional consumer. `module_key="purchase"`, actions `view`/`create`/
`confirm`/`receive` — the exact four the task's own spec names. Admin
always bypasses (same unconditional exemption every other admin-gated
mutation in this app already uses). **No `OWN`/`TEAM` scope is built for
Purchase Orders** — jdk_clean's own real design has zero ownership/
assignment dimension for POs (unlike Customer's `assigned_to_user_id`),
and inventing one now with no evidenced JDK requirement would be
speculative; each action here is a plain granted/not-granted check (no
grant = deny, the same semantics `permissions.md` already documents), not
a scoped filter with nothing to filter by.

## 12. Audit trail

Generic shared audit log, one row per PO create/status-change/approval/
receipt (status transitions only — per-line `received_quantity` deltas
aren't individually diffed, only the resulting status flip is). Receipts
are separately fully traceable via the `stock_movements` ledger itself,
arguably the richer trail. **Decision: reuse this shape** —
`audit_service.log_event` for create/update/status-change/receive
(one event per receive call, not per line), the `stock_movements` rows
themselves as the detailed per-line receiving record, same division of
responsibility.

## 13. Frontend / flow

List page (search + status filter) → PO detail page, no separate
receive screen/route — receiving is inline on the same page's line-items
table (an editable "receive now" quantity column appears directly in the
table once the PO is `confirmed`/`partially_received`, plus a small
shared "this delivery" panel below it). Effectively zero extra screens
from PO to receiving. **Decision: reuse this "no dead ends, no separate
receive route" philosophy directly** — jdk_erp additionally reuses its
own already-proven "flat list + a Modal for the child relationship"
pattern (`BomsPage.tsx`'s Manage Components/Calculate Requirements
dialogs) instead of jdk_clean's dedicated tabbed detail *page*: one
Purchase Orders list page, one "Purchase Order" Modal per row that shows
the header, the line-items table (Ordered/Received/Remaining), Manage
Lines controls while `draft`, and inline Receive controls while
`confirmed`/`partially_received` — never a separate route, never a
6-tab detail page.

## 14. Scope creep flagged — not replicated

No RFQ/quotation comparison, no vendor scoring beyond the single
`is_preferred` flag `SupplierMaterial` already has, no three-way
matching (no invoice entity exists or is added here), no blanket/standing
orders, no multi-step requisition-then-PO approval chain, no budget/
cost-center enforcement, no multi-currency handling. jdk_clean's own
code comments repeatedly explain these as *considered* omissions, not
oversights — the same discipline this build follows. `docs/modules/
purchase_orders.md`'s "Most important architectural rule" restates this
as the binding boundary for this module going forward.

## Bottom line

jdk_clean's Purchase Order/Receiving design is real, working, and mostly
worth reusing almost as-is: FK'd supplier/material selection, server-side
atomic numbering, a receive-as-action (not a GRN entity) shape, a
ledger-plus-snapshot stock model, and a deliberately narrow feature set
(no RFQ/budget/three-way-match). What's trimmed for this slice: the
`sent` status and the approval-threshold/overdue-escalation features
(unevidenced for JDK, explicit anti-scope-creep instruction), per-line
cancel, row-locking (no precedent in jdk_erp; replaced with the same
conditional-`UPDATE` concurrency shape `job_service.py` already
established), and the page-level permission matrix (replaced with
jdk_erp's own more capable, already-built, still-unused permission
engine). What's added beyond jdk_clean: a `warehouse_id` dimension on
both the PO and the stock ledger, since jdk_erp — unlike jdk_clean — has
a real `Warehouse` master to reference.

## Revision 2 — commercial document workflow audit

A second audit pass, for the task's own follow-up requirement that a PO
become a controlled, revisable commercial document with an official
PDF, native-email delivery, and a distinct supplier-confirmation event.
See `docs/modules/purchase_orders.md`'s own Revision 2 section (#21-#29)
for the resulting decisions; this section records what already existed
in jdk_erp to reuse versus what was a genuine gap.

1. **Native email**: `app/services/email_service.py` already exists,
   already sends through the organisation's own saved mailbox
   (`email_account_service`), and already supports a single binary
   attachment with a filename (`attachment_bytes`/`attachment_filename`
   params) — built for exactly this "generate a PDF, email it" case even
   though nothing used it yet. **Decision: reuse verbatim, no new email
   code.**
2. **PDF generation**: no PDF-rendering capability of any kind exists
   anywhere in jdk_erp (confirmed by grep — zero hits for "pdf" outside
   this session's own just-written RFQ docs). A genuine gap.
   **Decision: add `reportlab`** (a standard, pure-Python, no-system-
   dependency PDF library) as this module's one new dependency, and
   build the smallest PO-specific renderer that needs — no generic
   "document template engine."
3. **A4 letterhead/template**: no admin-configurable template entity
   exists either. `Organisation` (`app/models/organisation.py`) already
   carries `name`/`address`/`contact_email`/`contact_phone` — exactly the
   fields a small business's letterhead needs. **Decision: reuse these
   directly as the letterhead**, adding no new "template" entity or admin
   page — the task's own "keep this capability small, don't build a
   page designer" instruction is best served by not building a second
   configuration surface for data the organisation record already holds.
4. **Attachments/documents**: the generic `files` table
   (`app/models/file.py`) already built and already reused once by RFQ
   (`docs/audit/RFQ_AUDIT.md` #6) is the exact mechanism supplier
   confirmation evidence and generated revision PDFs both need.
   **Decision: reuse again, no new attachment mechanism.**
5. **Activity/communication history**: `AuditEvent`
   (`app/models/audit_event.py`) plus the existing admin-gated
   `GET /api/audit-events?entity_type=...&entity_id=...` endpoint
   (`app/api/audit_events.py`) already provide exactly the chronological,
   immutable event log the task's "Communication History" section
   describes. **Decision: reuse verbatim — no new history table, no new
   endpoint.** This does mean the Activity panel is admin-only on the
   frontend, the same boundary every other audit-trail view in this app
   already has.
6. **Revision/versioning**: no precedent anywhere (jdk_clean has none,
   confirmed in the original audit above; jdk_erp has none either, this
   being the first document type in this codebase with a revision
   concept at all). A genuine new data-model piece —
   `purchase_order_revisions`/`purchase_order_revision_lines`
   (`docs/modules/purchase_orders.md` #24), immutable snapshot rows, not
   a generic versioning framework applied speculatively to every table.
7. **Numbering**: the RFQ module's own `YY3NNNN` generator
   (`app/services/rfq_service.generate_rfq_number`) is the direct
   template for `YY5NNNN` — same shape, same mechanism, different fixed
   digit. **Decision: copy the pattern into
   `purchase_order_service.generate_po_number`, replacing the flat
   `PO000001` scheme this module originally shipped with** — not a
   third numbering mechanism, the same one already used twice.
8. **Complex features flagged and not built**: over-receipt tolerance
   (no audited evidence of an approved variance rule — stays hard-
   blocked), PO-level discount/tax (still no evidence), a revision-diff
   engine (the task's own text permits skipping this if it adds
   complexity — skipped, immutable history is relied on instead), a
   separate "communication module" (covered by #5 above already).

## Revision 3 — supplier payment audit

For the task's follow-up requirement: recording money paid to a
supplier against a PO, with history, evidence and an outstanding-amount
calculation — explicitly not a full accounts-payable/finance system.

1. **No supplier-side (accounts-payable) payment concept exists
   anywhere in jdk_erp** — confirmed by grep, consistent with Finance
   being an unbuilt future phase (`docs/ROADMAP.md` Phase 7).
2. **jdk_clean has a `Payment` model, but it is customer-side accounts
   receivable, not supplier-side payable** — `backend/app/models/payment.py`:
   `order_id`/`customer_id` FKs, no `supplier_id`/`purchase_order_id`
   anywhere. Its real, well-designed *shape* is still useful prior art
   to adapt (not reuse directly): free-text `method`/`reference` (no
   fixed enum — "how a customer actually pays isn't constrained by this
   app"), `notes`, and the general "recorded by ≠ who actually paid"
   distinction. **Not adapted**: its `acknowledged_at`/`acknowledged_by`
   two-person confirmation step — real there because Sales might
   optimistically log a customer's *claim* that money was sent before
   Finance confirms it landed; a supplier payment is the organisation's
   own outgoing payment, recorded by whoever already made/verified it,
   with no analogous "unconfirmed claim" risk to guard against. Also not
   adapted: `SoftDeleteMixin`-as-correction — the task explicitly wants
   a cancelled payment to stay visible in the same history, not
   filtered out by a soft-delete query, so this module uses a plain
   `status` field instead.
3. **Decision: no payment-terms enum.** `PurchaseOrder.payment_terms`
   (already built in Revision 2, `docs/modules/purchase_orders.md` #4)
   stays free text — no jdk_clean precedent for a fixed terms enum, and
   introducing one now with no evidenced JDK category list would be
   speculative.
4. **Decision: no payment-before-receipt enforcement.** The task's own
   text requires this be conditional on an actual audited business
   rule, and simultaneously requires that both "receipt before payment"
   and "payment before receipt" remain valid situations. No such rule
   was found audited anywhere (jdk_clean has none to find, since it has
   no supplier payment concept at all). Building an enforced gate now
   would be pure invention — the PO's Paid/Outstanding figures are
   shown for a human to act on instead.
5. **Decision: no overpayment allowance.** No audited evidence permits
   exceeding the payable amount — stays hard-blocked, the same "no
   tolerance without evidence" discipline the receiving guard already
   established (Revision 1 above).
6. **Numbering**: no existing supplier-payment numbering to reuse
   (nothing exists). **Decision: the same `YYxNNNN` generator shape
   used twice already (RFQ's `3`, PO's `5`), extended with a third fixed
   digit (`7`) for this document type** — not a fourth mechanism, the
   same one a third time.
7. **Decision: reuse, not rebuild** — the generic `files` attachment
   system (its third real consumer after RFQ responses and PO
   revisions/documents), `audit_service`, `authorization_service`
   (a new `purchase_payment` module_key, so an organisation can grant
   its Accounts/Finance team payment permissions independently of
   Procurement's own `purchase` permissions — directly answering the
   task's "a finance person should be able to change payment status"
   requirement without inventing a department/role concept that doesn't
   exist), and the existing `Numeric(14, 4)` decimal-amount convention
   every other monetary column in this codebase already uses (never a
   float).
8. **Supplier invoice**: no supplier-invoice entity exists in jdk_erp,
   confirmed by the same grep as #1. **Decision: payment stays PO-based**
   only, per the task's own explicit instruction — no invoice concept is
   introduced in this pass.

## Revision 4 — goods receipt / GRN audit

For the task's follow-up requirement: a distinct Goods Receipt document
between Purchase Order and Inventory — "these materials physically
arrived against this PO" — replacing the plain receive-as-action shape
Revision 1 (#8) deliberately chose. `/home/user/jdk_clean` is not
reachable in this session (confirmed — the checkout simply isn't present
here), so this revision reasons from Revision 1's own already-completed,
file:line-cited jdk_clean audit rather than re-auditing from scratch;
nothing below overturns a Revision 1 finding, it only reuses them for a
new decision.

1. **jdk_clean has no separate GRN/goods-receipt entity either** (Revision
   1 #8, already established with citations) — this is not new jdk_clean
   prior art to reuse, it is the confirmed absence of any. Building a real
   `PurchaseOrderReceipt` header+lines entity now is a genuine, explicit
   supersession of Revision 1's "reuse jdk_clean's receive-as-action shape"
   decision, driven by this task's own explicit requirement for a
   traceable document (`Inventory Entry -> Receipt -> PO -> Supplier`),
   not by new jdk_clean evidence.
2. **No incoming QC/inspection workflow exists anywhere to integrate
   with.** `app/models/raw_material.py`'s own docstring already records
   that jdk_clean's `inspection_required`/`certificate_required`/
   `qc_notes` fields were "never actually checked at receipt in
   jdk_clean despite existing" — confirmed dead, not merely unbuilt.
   Grepping jdk_erp itself for QC/inspection/accepted-quantity/
   rejected-quantity turns up nothing outside that same docstring.
   **Decision: no accepted-vs-rejected quantity, no QC gate.** The task's
   own instruction is explicit here — do not invent QC without an
   audited requirement. A receipt's `quantity` is the full physical
   receipt, all of it available stock.
3. **No payment-before-receipt rule exists** (Revision 3 #4, already
   established) and `PurchaseOrder.payment_terms` is free text, not a
   structured "requires advance payment" flag (Revision 3 #3) — there is
   no machine-readable condition to gate on. **Decision: unchanged from
   Revision 3** — receipt stays independent of payment status; the PO
   screen shows both figures side by side for a human to act on, no
   automatic block.
4. **UOM**: no purchase-UOM/conversion field exists on `PurchaseOrderLine`
   (Revision 1 #2/#5) — a line's quantity is always in the material's own
   `unit_of_measure_id`, with no second, user-enterable unit anywhere in
   the purchase flow. **Decision: the same "no purchase-UOM field, so no
   mismatch is representable" design carries over to receipt lines
   unchanged** — a receipt line's quantity is a plain number against a
   `purchase_order_line_id`, in that line's already-fixed material/unit;
   there is no UOM input to silently misinterpret. This satisfies the
   task's #7/#8 rules by construction, the same way Revision 1 already
   did for PO lines, rather than by adding a validation check.
5. **Over-receipt**: Revision 1 (#10) already hard-blocks over-receipt
   with no tolerance, enforced by an atomic conditional `UPDATE ...
   WHERE received_quantity + :qty <= quantity`. **Decision: reuse this
   exact guard, moved to receipt-posting time** — still no tolerance
   invented, no jdk_clean evidence of one to preserve either (Revision 1
   found none).
6. **Ledger**: `StockMovement` (immutable, append-only) +
   `RawMaterialInventory` (derived snapshot) already exist as the one
   authoritative stock structure (Revision 1 #9). **Decision: no second
   ledger, no `products.quantity`-style duplicate field.** Posting a
   receipt line still calls the same `inventory_service` entry point;
   only the `reference_type` written changes, from the old
   `purchase_order_line` (kept as a historical constant — already-written
   rows keep it forever, never migrated) to a new
   `purchase_order_receipt_line`, so a movement now traces directly to
   the receipt that created it, then to the PO, per the task's own
   traceability requirement. A reversal is a second, negative-quantity
   movement in the same ledger (`receipt_reversal`), not a
   destructive update — no jdk_erp precedent exists for ever editing a
   `StockMovement` row, and none is introduced here.
7. **Duplicate posting**: Revision 1 dropped jdk_clean's `invoice_number`
   dedup guard as unevidenced (#10) and relies on the atomic
   conditional-`UPDATE` shape plus frontend request-in-flight discipline.
   **Decision: extend the same discipline** — a receipt's `status` field
   is itself the idempotency guard (`draft -> posted` is only reachable
   once; posting is an atomic `UPDATE ... WHERE status = 'draft'`, so a
   duplicate/racing post request finds zero rows to update and is
   rejected, never double-applies the inventory effect), not a second
   `invoice_number`-style field.
8. **Editing a posted receipt / correction**: no reversal or correction
   mechanism exists anywhere in jdk_erp to reuse (nothing comparable has
   been built yet). **Decision: a posted receipt is never edited.** A
   `draft` receipt (no inventory effect yet) can simply be cancelled and
   discarded. A `posted` receipt can only be `reversed` — a required
   reason, a full offsetting negative stock movement per line, the PO's
   `received_quantity` stepped back down by the same atomic guard used
   for receiving — never a partial in-place quantity edit. The original
   receipt and its original line quantities remain visible and unchanged
   forever, the same "cancel and record a fresh one, never edit"
   discipline Revision 3 already established for payments. If the actual
   correct quantity is known, the workflow is reverse, then create and
   post a new, correct receipt — not a quantity-editing UI, which the
   task itself never asks for and no evidence supports building.
9. **Numbering**: **the same `YYxNNNN` generator shape used three times
   already (RFQ's `3`, PO's `5`, Payment's `7`), extended with a fourth
   fixed digit (`9`)** for Goods Receipt — not a new mechanism.
10. **Warehouse**: `PurchaseOrder.warehouse_id` is already the PO's one
    immutable destination warehouse (Revision 2 #1); jdk_erp has exactly
    one real `Warehouse` master today (`docs/audit/WAREHOUSES_AUDIT.md`).
    **Decision: a receipt inherits its PO's warehouse_id outright, with
    no separate warehouse-picker step** — the task's own instruction is
    to make single-warehouse receiving "effortless," and there is no
    evidenced case for receiving a PO's materials into a warehouse other
    than the one it was ordered for.
11. **Documents/PDF**: `purchase_order_pdf_service.py` (Revision 2 #2) is
    the one PDF-generation capability in this codebase, built narrowly
    per-document rather than as a generic templating engine. **Decision:
    add a second, equally narrow `purchase_order_receipt_pdf_service.py`
    following the exact same shape** (same letterhead source, same
    reportlab primitives) — not a generic document engine, not a second
    letterhead concept.
12. **Reuse, not rebuild**: the generic `files` attachment system (a
    fourth consumer, `entity_type="purchase_order_receipt"`), the same
    `purchase_scope` permission actions already gating every other PO
    lifecycle action (Revision 1 #11 — no finer-grained receipt-specific
    module_key; `purchase:receive` already exists and already means
    "the receiving step of this PO's lifecycle"), `audit_service`, and
    the `Numeric(14, 4)` quantity convention every other line-item column
    already uses.
13. **What's removed, not merely superseded**: the old single-call
    `POST /purchase-orders/{id}/receive` action and
    `purchase_order_service.receive_lines` are deleted outright, not kept
    alongside the new flow — Revision 1's receive-as-action design is
    fully replaced by the receipt document, per this task's explicit
    requirement, not layered on top of it. Every already-written
    historical `StockMovement` row from the old path is untouched (its
    `reference_type="purchase_order_line"` stays exactly as it was
    written — historical fact, never rewritten).
