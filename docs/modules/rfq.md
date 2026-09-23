# Procurement: RFQ (Request for Quotation)

Precedes Purchase Orders in `docs/ROADMAP.md` Phase 4 — Procurement &
Inventory: `RFQ -> Supplier Response -> Decision -> Purchase Order ->
Receipt -> Inventory`. Audited against jdk_clean first
(`../audit/RFQ_AUDIT.md`), which has no RFQ concept at all — this module
is built fresh from its own spec and jdk_erp's own existing conventions.

## 1. Purpose

Ask one supplier for pricing/availability on specified raw materials,
capture what they actually offer (as evidence, not re-typed data), let
an authorized user explicitly decide, and — if selected — create the
Purchase Order from that decision with no re-entry. RFQ is a request; it
never affects inventory, and it never commits to buying anything by
itself.

## 2. RFQ header and lines

Header: `rfq_number` (system-generated, immutable — #7), `supplier_id`
(FK, immutable after creation, one RFQ = one supplier — #10),
`rfq_date`, `required_delivery_date` (optional), `notes` (optional),
`status`, decision fields (`decided_by_user_id`, `decided_at`,
`decision_note`, `selected_response_id`), `purchase_order_id` (set only
once converted), `organisation_id`, `created_at`/`updated_at`. Lines:
`raw_material_id` (FK, immutable, active-and-same-organisation, never
free text), `quantity` (> 0, expressed in the material's own
`unit_of_measure_id` — the identical "no purchase UoM" decision
`docs/modules/purchase_orders.md` #5 already made, applying here for the
same reason: RFQ is requesting the same material the eventual PO/receipt
will use). No price field on an RFQ line — an RFQ is a request, not a
commitment; pricing only ever appears via the supplier's captured
response (#5) or the PO created from a decision (#8).

## 3. Lifecycle

```text
draft
  |
  v
issued
  |
  v
response_received
  |
  v
selected / rejected
  |
  v
converted
```

plus `cancelled`, reachable from `draft`, `issued`, `response_received`,
or `selected` (never from `rejected`/`converted` — both are already
terminal). `draft -> issued` requires at least one line (the same
"cannot confirm/activate empty" gate `docs/modules/purchase_orders.md`
#7 and `docs/modules/boms.md` #10 already established) and marks the
real fact that the request actually went out to the supplier, whatever
channel carried it (phone, WhatsApp, email) — the system never sends
anything itself (#4). `issued -> response_received` happens automatically
the first time a response is captured (#5), the same "side effect of an
action, never a direct status-change target" discipline
`docs/modules/purchase_orders.md` #4 already established for
`partially_received`/`fully_received`. `response_received -> selected`
or `-> rejected` only happens via the explicit decision action (#6) —
capturing a response never itself decides anything. `selected ->
converted` only happens via the convert action (#8). Cancelling requires
a non-blank reason, same as Purchase Order (`docs/modules/purchase_orders.md`
#4).

## 4. Issuing — no email, no PDF

`issued` is a plain status transition. This module does not generate a
document or send anything through the application — the request itself
travels through whatever normal channel the business already uses
(phone call, WhatsApp, email written by hand). Nothing here is a
document-generation or communication feature; see #20 for the boundary
this deliberately does not cross.

## 5. Supplier response capture

A response is evidence, not a structured re-entry of the supplier's
quote. `POST /api/rfqs/{id}/responses` creates an `RfqResponse`
(`response_received_at`, optional short `note`, `created_by_user_id`)
and links one or more already-uploaded files to it via the existing
generic file system (`entity_type="rfq_response"`,
`entity_id=response.id` — `app/models/file.py`, `../audit/RFQ_AUDIT.md`
#6). No structured price/quantity/delivery fields are captured here —
the attached document (screenshot, PDF, photo) *is* the record of what
the supplier offered. Multiple `RfqResponse` rows are supported per RFQ
(a supplier sending a revised quote later is a new response, never an
edit to the first one — #9's historical-integrity rule), but always for
the *same* supplier (#10) — never a second supplier's response on the
same RFQ.

## 6. Decision

`PATCH /api/rfqs/{id}/decision`: `{decision: "selected" | "rejected",
selected_response_id?, note?}`. Only valid from `response_received` — a
decision without a captured response is meaningless and is rejected
server-side. `selected_response_id` is required when `decision ==
"selected"` (identifying which captured response the decision is based
on) and must reference a response that actually belongs to this RFQ.
Records `decided_by_user_id`/`decided_at`/`decision_note` and sets
`status` to `selected` or `rejected` — no separate "decision" entity or
approval chain; this is one explicit, auditable action a permitted user
takes (`../audit/RFQ_AUDIT.md` #7), never an automatic "best price"
selection (#10).

## 7. Numbering

`YY3NNNN` — 2-digit year, a fixed `3` (RFQ document-type digit), a
4-digit sequence that **resets every calendar year**, per organisation.
`app/services/rfq_service.generate_rfq_number` counts existing RFQs for
the caller's organisation whose `rfq_number` starts with this year's
`YY3` prefix, adds one, formats, and retries against the unique
constraint under `IntegrityError` — the identical discipline every other
server-side code generator in this codebase already uses
(`_generate_supplier_code`, `_generate_po_number`, ...), just scoped to
the current year because this one document type's numbering rule
requires it (`../audit/RFQ_AUDIT.md` #2). Server-generated only, never
client-supplied, stable after creation.

## 8. RFQ -> Purchase Order

`POST /api/rfqs/{id}/convert-to-po`: `{warehouse_id, lines: [{rfq_line_id,
unit_price}]}`. Only valid from `selected`. Supplier, raw materials, and
quantities are carried forward automatically from the RFQ and its lines
— never re-entered; `warehouse_id` (an RFQ has no warehouse dimension —
`docs/modules/purchase_orders.md` #2 requires one on every PO) and each
line's `unit_price` (never captured as structured data anywhere upstream
— #2/#5) are the only new input, exactly matching the task's own "this
is the only additional entry required" rule. Implemented by
`purchase_order_service.create_purchase_order_with_lines` — the same
function the plain "New Purchase" flow itself now uses (extracted for
this reuse, `../audit/RFQ_AUDIT.md` #5) — followed by stamping
`Rfq.purchase_order_id` and flipping `Rfq.status` to `converted`, all in
one transaction (#12). Only `selected` RFQs can convert, and a
successful conversion immediately moves the RFQ to `converted`, which is
no longer a valid source for a second conversion — the same
"transition-guard doubles as the idempotency guard" discipline
`docs/modules/purchase_orders.md` #8 already established, so a repeated
submission cannot create a second Purchase Order.

## 9. Historical integrity

An `RfqLine`'s `quantity` is never rewritten by a captured response, no
matter what the supplier actually offers — the original request stays
exactly as requested (task's own "requested: 100 bags" example). A
captured `RfqResponse` and its attached files are never edited or
replaced after creation — a revised quote is a new `RfqResponse` row,
preserving the full history of what was received and when (mirrors
`docs/modules/purchase_orders.md` #6's "never silently rewrite historical
receipts" rule, applied to responses).

## 10. One supplier per RFQ, no vendor comparison

An RFQ's `supplier_id` is immutable after creation, same discipline as
`PurchaseOrder.supplier_id`. No vendor scoring, automatic "best supplier"
selection, bidding rounds, or procurement-event/multi-supplier comparison
UI exists — the business user makes every decision (#6), never an
algorithm (`../audit/RFQ_AUDIT.md` #8).

## 11. Inventory boundary

Creating, issuing, capturing a response against, or deciding on an RFQ
never touches inventory — neither does creating the Purchase Order it
converts into. Only a PO's own receive action
(`docs/modules/purchase_orders.md` #8/#9) is stock-affecting. This
module writes nothing to `stock_movements`/`raw_material_inventory` at
any point.

## 12. Transaction safety

The decision action (status + decision fields) and the convert action
(PO creation + line copy + `Rfq.purchase_order_id` stamp + `Rfq.status`
flip) are each one database transaction — partial state (a PO created
without the RFQ being marked `converted`, or vice versa) is never
possible. Repeated submission of convert cannot create a duplicate PO
(#8's transition-guard-as-idempotency-guard).

## 13. Permissions

Reuses `authorization_service` (`docs/modules/permissions.md`), the
second real module to use it after Purchase Orders.
`module_key="rfq"`, actions: `view`, `create` (covers create/edit-draft/
line management, mirroring Purchase's own "create" action shape),
`issue`, `capture_response`, `decide`, `convert`. Admin/super_admin
always bypass; everyone else needs an explicit grant — no `OWN`/`TEAM`
scope, same reasoning as Purchase Orders
(`../audit/RFQ_AUDIT.md` #7).

## 14. Organisation isolation and database integrity

`rfqs`/`rfq_responses` are organisation-scoped (`OrganisationScopedMixin`);
`rfq_lines` are a child of an already-scoped `Rfq`, same shape as
`purchase_order_lines`. `supplier_id`/`raw_material_id`/`warehouse_id`
(at conversion) are all validated active-and-same-organisation on every
write. `UniqueConstraint(organisation_id, rfq_number)`. A cross-
organisation `rfq_id`/`response_id`/attached file all 404, never 403 —
existence is never confirmed to a caller outside the organisation.

## 15. Attachments

Reuses the existing generic `files` system exactly as built
(`app/models/file.py`, `app/services/file_service.py`,
`POST`/`GET`/`DELETE /api/files`) — no new upload/storage/download code.
An access checker is registered for `entity_type="rfq_response"`
(`app/core/entity_access.py`) that resolves the response's owning RFQ
and applies the same organisation-scope + `view` permission check the
RFQ API itself uses, so a file inherits the access rules of the RFQ it
belongs to (`docs/modules/file_storage.md` #5). The `FileUploadField`
common component (already built, previously unused outside the style
guide) is this module's first real consumer.

## 16. List and find UX

One list page (`DataTable`/`FilterBar`/`ActionMenu`/`Badge`): RFQ
number (searchable), supplier, date, status, response status, PO status
(derived — "Converted" links to the PO once one exists). Reuses every
common list primitive Purchase Orders already established — no RFQ-
specific table code.

## 17. Navigation and no dead ends

A new "Procurement" sidebar group (shared with Purchase Orders, created
alongside them) containing "RFQs" — `Home -> Procurement -> RFQs`, 2
navigations. One Modal per RFQ (same reused
list-plus-child-relationship-Modal pattern `docs/modules/purchase_orders.md`
#17 already established from `BomsPage.tsx`) carries the entire
lifecycle — header, lines, responses (with inline attachment
preview/download), decision, and (once selected) the convert-to-PO
form — never a separate route per stage. Every status exposes its one
obvious next action: `draft` -> Issue; `issued` -> Capture Response;
`response_received` -> Make Decision; `selected` -> Create Purchase
Order; `rejected`/`cancelled` -> read-only, no misleading action;
`converted` -> View Purchase Order (a direct link, since
`purchase_order_id` is already known).

## 18. Performance

No search engine, caching layer, or background processing — matches
`docs/modules/purchase_orders.md` #19 exactly, same expected scale.

## 19. Testing

Focused on real business behaviour, not CRUD: RFQ number format/yearly
reset/concurrency-safety; the full lifecycle end-to-end (draft -> issue
-> capture response -> decide selected -> convert -> PO exists with the
right supplier/lines, and inventory is untouched throughout); a rejected
RFQ has no convert path; a cancelled RFQ at any valid cancellation point;
double-submitting convert never creates a second PO; cross-organisation
isolation on the RFQ and its attachments; the RFQ's original requested
quantity is never altered by a captured response.

## 20. Most important architectural rule — document/PDF/email boundary

This module does not generate documents and does not send anything.
"Issue" is a status fact, not a system action; "capture response" is
evidence storage, not data re-entry; the RFQ itself travels to the
supplier however the business already does that. No A4 template, PDF
generation, or native-email integration is built or extended here — none
is required by this module's own actual scope, and adding one now would
be exactly the speculative document/communication infrastructure this
codebase's engineering principles rule out building ahead of a proven
need. If a future module genuinely needs to generate and email an
official document (an Invoice, a Delivery Note), that is its own
audited, scoped piece of work — not something this module should invent
a shared framework for pre-emptively.

## Implementation approach

Per `../ENGINEERING_PRINCIPLES.md` §16: see `../audit/RFQ_AUDIT.md`.
Reuses jdk_erp's own `files`/`entity_access` attachment system (its
first real consumer), the `ALLOWED_*_TRANSITIONS` status-machine
convention `docs/modules/purchase_orders.md` established, the
`authorization_service` permission engine (its second real consumer),
`FileUploadField` (its first real consumer outside the style guide), and
a `purchase_order_service.create_purchase_order_with_lines` function
extracted so both the plain "New Purchase" flow and this module's
convert action share one PO-creation implementation.
