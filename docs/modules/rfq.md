# Procurement: RFQ (Request for Quotation) — v2

Precedes Purchase Orders in `docs/ROADMAP.md` Phase 4 — Procurement &
Inventory: `RFQ -> Supplier Response(s) -> Decision -> Purchase Order ->
Receipt -> Inventory`. Revises the v1 spec — see
`../audit/RFQ_AUDIT_V2.md` for exactly what changed and why (v1's own
audit: `../audit/RFQ_AUDIT.md`). Sections below are renumbered; where a
v1 decision is unchanged, it says so and moves on rather than re-arguing
it.

## 1. Purpose

Ask one or more suppliers for pricing/availability on specified raw
materials, capture what each actually offers as real comparable data,
let an authorized user explicitly decide, and — if selected — create the
Purchase Order from that decision with no re-entry of anything already
on record. RFQ is a request; it never affects inventory, and it never
commits to buying anything by itself. Unchanged from v1.

## 2. RFQ header

One form page (`/rfqs/new`, `/rfqs/{id}/edit`) creates, edits and submits the whole RFQ:
`POST /api/rfqs` / `PUT /api/rfqs/{id}` with the same body.
Viewing an RFQ is also a page (`/rfqs/{id}`): details, comparison, per-supplier
PDF / email and the action buttons. Saving the form lands there. Approve /
Reject, quote capture, cancel and PO generation stay dialogs over it.

- Auto: `rfq_number` (#10 — the form shows the next number from
  `GET /api/rfqs/next-number`; it is assigned on save), `rfq_date`
  (today), `requested_by_user_id` (session user) — never client-supplied,
  never edited.
- Required: `required_delivery_date` (not in the past).
- `priority` (`normal` | `urgent`, display/filter only).
- No department: an RFQ doesn't reference or depend on one (migration
  `0036` dropped `rfqs.team_id`). The form has no notes field.
- `submit`: `false` saves a draft; `true` issues the next revision (#9).

Also carries `status`, `revision_number`, decision fields,
`purchase_order_id`, `organisation_id`, timestamps. No price at header
or line level — pricing only comes from a supplier's quote (#5).

## 3. RFQ items — mandatory

At least one item. Per item:

- `raw_material_id` — required, active, same organisation.
- `quantity` — required, > 0.
- `unit_of_measure_id` — required, chosen from the Units master data,
  defaulting to the item's own unit. Only accepted when it converts to
  the item's own unit (`app/services/uom_conversion.py`), so the PO step
  can always express it in the item's unit (#8).
- `remarks` — optional specification.

## 4. Suppliers

At least one registered, active supplier (`supplier_ids`, no
duplicates). The picker lists matches after 2 typed letters. Each
supplier is one `RfqSupplierInvitation` (`sent` | `quoted` | `declined`),
reconciled by supplier on edit so a kept supplier keeps its PDF history.
`POST .../invitations/{id}/decline` flags a supplier's "no" and changes
nothing else.

## 5. Supplier response capture

`POST /api/rfqs/{id}/invitations/{invitation_id}/responses` creates an
`RfqResponse`: `invitation_id` (not `rfq_id` directly — a response always
belongs to one supplier's invitation), `response_received_at`,
`supplier_quotation_number` (optional — the supplier's own reference),
`quotation_date` (optional), `valid_until` (optional, not before
`quotation_date`), `payment_terms`/`delivery_terms`/`freight_terms`
(optional free text — "30 days", "included", etc.), `note` (optional),
`created_by_user_id`.

Each response has `RfqResponseLine` rows, one per `RfqLine` it quotes:
`rfq_line_id` (FK, must belong to this RFQ), `unit_price` (required,
> 0), `delivery_days` (optional integer ≥ 0), `remarks` (optional). A
response does not have to quote every line — a supplier can decline part
of the request — but it must quote at least one (a supplier who quotes
nothing is recorded by declining the invitation, #4), each line at most
once, and every `RfqResponseLine` must reference a real line on this RFQ
(422 otherwise — never silently dropped).

Attached files still work exactly as in v1: uploaded via the existing
generic file system (`entity_type="rfq_response"`,
`entity_id=response.id`), now optional supporting evidence (the
supplier's actual PDF/screenshot), no longer the sole record.

Multiple `RfqResponse` rows are still supported per invitation — a
supplier revising their quote is a new response, never an edit to the
first one (#12) — but always for the same invitation's supplier.

Capturing a response flips its invitation's `status` to `quoted` and the
RFQ's own `status` to `response_received` if it isn't already past that
point. Only valid while the RFQ is `issued` or `response_received`.

## 6. Comparison

Not a new entity or endpoint — a read-only shape assembled from existing
data: `GET /api/rfqs/{id}` returns each invitation with its responses and
each response's lines, and the frontend renders one table — RFQ line
down the rows, one column per supplier that has quoted (their latest
response), `unit_price` (and `delivery_days` if present) in each cell.
No total/ranking/highlight is computed — the table is informational, the
decision in #7 is still entirely the human's.

## 7. Approval

`PATCH /api/rfqs/{id}/decision`: `{decision: "selected" | "rejected",
selected_response_id?, note?, file_ids?, quantities_confirmed?}`. Only
from `response_received`.

- **Approve** (`selected`) is based on the document received from the
  supplier: `file_ids` (PDF/PNG/JPEG via `POST /api/files`, attached as
  `entity_type="rfq_acceptance"`) and `quantities_confirmed=true` — the
  agreed quantities equal the requested ones. The user is taken straight
  to PO generation (#8).
- **Agreed quantity differs** → no approval.
  `POST /api/rfqs/{id}/raise-new` `{lines: [{rfq_line_id, quantity}]}`
  cancels this RFQ ("replaced by RFQ N") and creates a new **draft** —
  same priority, suppliers and items, agreed quantities —
  opened in the RFQ form to check and submit. One transaction.
- **Once approved** the RFQ can't be revised; it can only go to a PO or
  be cancelled.
- **Reject**: terminal. Nothing further.

## 8. PO generation

`POST /api/rfqs/{id}/convert-to-po`: `{expected_delivery_date,
payment_terms, supplier_reference?, notes?, lines?: [{rfq_line_id,
unit_price?}]}`. Only from `selected` with the supplier document on file.

- Supplier: the approved quotation's supplier. Items/quantities: the RFQ.
- No delivery location or currency: the organisation's one warehouse,
  always KWD. `expected_delivery_date`
  (required, not past — pre-filled from the RFQ's Required By).
  `payment_terms` (required — pre-filled from the quotation).
  `supplier_reference` pre-filled from the quotation number.
- Unit prices pre-filled from the approved quotation, editable; a line
  without a price is rejected. The PO keeps these final agreed values as
  its own — never re-read from the quotation.
- PO lines keep the RFQ's unit, quantity and agreed price (2 MT at
  85.000/MT stays 2 MT at 85.000). The unit's ratio to the item's own
  unit is stored on the line so receiving posts stock correctly.
- Built by `purchase_order_service.create_purchase_order_with_lines`,
  stamps `Rfq.purchase_order_id`, `status → converted`, one transaction;
  the transition guard blocks a second PO. The user lands on Purchase
  Orders.

## 9. Lifecycle and revisions

```text
draft --submit--> issued (Rev 1) --quote--> response_received --accept--> selected --PO--> converted
                    |  ^                                        \--reject--> rejected (stop)
                    |  '-- revise: submit Rev N+1 (only before the first quote)
cancelled <- draft / issued / response_received / selected (reason required)
```

- A draft can be edited and saved any number of times, then submitted.
- An issued RFQ can be revised (same form, always re-submitted) until
  the first quote is captured: `revision_number` + 1 and a new PDF per
  supplier. Earlier PDFs are kept.
- `PATCH /api/rfqs/{id}/status` only cancels.

## 10. Numbering

`YY3NNNN`, per-organisation, resets yearly. Unchanged from v1
(`app/services/rfq_service.generate_rfq_number`).

## 11. RFQ PDF — letterhead, download, email

Every submit renders one A4 PDF per supplier
(`app/services/rfq_pdf_service.py`, reportlab — same as the PO PDF),
stored via the generic files system (`entity_type="rfq_invitation"`),
exposed as `invitations[].pdf_file` and downloaded via `/api/files/{id}`.

`POST /api/rfqs/{id}/invitations/{invitation_id}/send` emails that
supplier's latest PDF through the organisation mailbox
(`email_service`), stamps `last_emailed_at`, and audits success/failure.
Needs a supplier email and a configured mailbox.

**Admin → Settings → Documents** (`/api/document-templates/rfq`,
admin only): a full-page letterhead image (PNG/JPEG) drawn behind every
page, top/bottom margins that keep content clear of it, and the opening
text, terms and signature block. Applies to PDFs generated afterwards.
Without a letterhead the organisation name/address is printed instead.

## 12. Historical integrity

Unchanged from v1: an `RfqLine`'s `quantity` is never rewritten by a
captured response. A captured `RfqResponse`, its lines, and its attached
files are never edited or replaced after creation — a revised quote is a
new `RfqResponse` row against the same invitation.

## 13. Inventory boundary

Unchanged from v1: nothing in this module, including the comparison view
and invitation management, ever touches
`stock_movements`/`raw_material_inventory`.

## 14. Transaction safety

Unchanged from v1: decision and convert actions are each one
transaction. Response capture (response + its lines + invitation/RFQ
status + attachment linking) is one transaction too.

## 15. Permissions

Reuses `authorization_service`: `module_key="rfq"`, actions `view`,
`create` (create/edit-draft/line management/manage invitations —
invitations are part of the draft, not a separate permission), `issue`,
`capture_response` (also covers declining an invitation — both record a
supplier's answer), `decide`, `convert`. Admin/super_admin always bypass;
no `OWN`/`TEAM` scope.

## 16. Organisation isolation and database integrity

`rfqs`/`rfq_responses` are organisation-scoped. `rfq_lines`,
`rfq_supplier_invitations` and `rfq_response_lines` are children of an
already-scoped `Rfq`/`RfqResponse` (no `organisation_id` of their own).
`supplier_id`/`raw_material_id` are validated
active-and-same-organisation on every write. An invitation id is always
resolved within the RFQ in the path. A cross-organisation id anywhere in
this module 404s, never 403s.

## 17. Attachments

Unchanged from v1: the existing generic `files` system,
`entity_type="rfq_response"`, same access-checker registration.

## 18. List and comparison UX

List page (`DataTable`/`FilterBar`/`ActionMenu`/`Badge`): RFQ number,
date, priority badge, "Suppliers" (invited count,
and once any have quoted, e.g. "2 of 3 quoted"), status, PO status.
Filters: RFQ number search, priority; the API also filters by `status`,
and `supplier_id` (RFQs that supplier was invited to).

Inside the RFQ record: grouped by invited supplier — each invitation
shows its own status, its own capture-response action, and its own
response history. Once two or more invitations have a response, the
comparison table (#6) is shown above the per-supplier detail. Every
status exposes its one obvious next action: `draft` -> Add Materials /
Invite Suppliers -> Issue; `issued` -> Capture Response (per invitation);
`response_received` -> compare, then Make Decision; `selected` -> Create
Purchase Order (pre-filled, not blank); `rejected`/`cancelled` ->
read-only; `converted` -> View Purchase Order.

Still one Modal per RFQ carrying the whole lifecycle.

## 19. Performance

Unchanged from v1: no search engine, caching layer, or background
processing. The list and detail endpoints assemble the nested shape in a
fixed number of queries per page, never one per row.

## 20. Testing

`backend/tests/test_rfqs.py`: numbering format/yearly reset; header
stamping (requester never client-supplied, team isolation, priority);
line remarks; issue guards (no lines / no invitations); duplicate,
inactive and cross-organisation invitations; invitations draft-only; the
full multi-supplier flow (capture -> comparison shape -> select one
supplier -> convert pre-filled -> PO has that supplier and quoted prices,
inventory untouched); convert override; unquoted line requires a manual
price (and nothing is created until it has one); double convert; a
response line referencing another RFQ's line is rejected; two
invitations capture and revise independently; declining is a flag only;
selecting another RFQ's response is rejected; rejected has no convert
path; cancel requires a reason; list filters; cross-organisation RFQ,
comparison, capture and decline all 404; permission default-deny.

## Migration

`backend/migrations/versions/0032_rfq_v2_invitations_and_structured_responses.py`
carries v1 data forward (each v1 `supplier_id` becomes one invitation,
each response is re-pointed to it) — see `../audit/RFQ_AUDIT_V2.md` #4.

`0033_rfq_units_pdf_letterhead.py` adds `rfqs.revision_number` (issued
RFQs start at 1), `rfq_lines.unit_of_measure_id` (backfilled from each
item's own unit) and `required_by_date`,
`rfq_supplier_invitations.last_emailed_at`, and `document_templates`.
