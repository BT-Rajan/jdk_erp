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

`rfq_number` (system-generated, immutable — #10), `rfq_date`,
`required_delivery_date` (optional), `team_id` (optional FK to `teams` —
this codebase's existing "department" concept, per
`docs/modules/teams.md`; reused rather than inventing a second one,
validated active-and-same-organisation), `requested_by_user_id`
(auto-stamped from the session user at creation, never client-supplied,
never edited), `priority` (`normal` | `urgent`, default `normal` — a
plain field, not a workflow: it changes nothing server-side, it's a
filter/sort hint and a badge), `notes` (optional), `status`, decision
fields (`decided_by_user_id`, `decided_at`, `decision_note`,
`selected_response_id`), `purchase_order_id` (set only once converted),
`organisation_id`, `created_at`/`updated_at`.

No `supplier_id` on the header anymore — see #4. No price field at
header or line level — an RFQ line is still a request, never a
commitment (unchanged from v1); pricing only ever appears via a
supplier's captured response (#5) or the PO created from a decision
(#8).

## 3. RFQ lines

`raw_material_id` (FK, immutable, active-and-same-organisation, never
free text), `quantity` (> 0, expressed in the material's own
`unit_of_measure_id` — the "no purchase UoM" decision
`docs/modules/purchase_orders.md` #5 already made, unchanged here),
optional `remarks` (free text — grade/size/quality note, e.g. "fine
washed"). `remarks` is the only new field on a line versus v1: a real,
low-risk, non-price piece of the request itself.

## 4. Supplier invitations

`RfqSupplierInvitation`: `rfq_id`, `supplier_id` (FK, immutable after
creation, active-and-same-organisation), `status` (`sent` | `quoted` |
`declined`), `invited_at`. `UniqueConstraint(rfq_id, supplier_id)` — a
supplier can't be invited twice to the same RFQ (409). One RFQ can have
one invitation or several; the lifecycle and every other rule in this
document is identical either way.

- `POST /api/rfqs/{id}/invitations` `{supplier_id}` /
  `DELETE /api/rfqs/{id}/invitations/{invitation_id}` — draft only
  (invitations are part of the draft).
- `quoted` is only ever a side effect of a response being captured
  against the invitation (also from `declined` — a supplier who said no
  and later quoted anyway is a real quote).
- `POST /api/rfqs/{id}/invitations/{invitation_id}/decline` — a manual
  "this supplier said no / went unanswered" flag with no further
  behaviour: it doesn't change the RFQ's status, other invitations, or
  any captured response. Only a `sent` invitation on an `issued`/
  `response_received` RFQ can be declined.

This does not reintroduce vendor scoring, bidding rounds, or a
procurement-event entity — it's one join row per invited supplier, and
the decision in #7 is still a human picking one response, never an
algorithm.

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

## 7. Decision

`PATCH /api/rfqs/{id}/decision`: `{decision: "selected" | "rejected",
selected_response_id?, note?}`. Unchanged from v1 except that
`selected_response_id` can reference a response belonging to any invited
supplier on this RFQ (never another RFQ's — 422). Only valid from
`response_received`. Records `decided_by_user_id`/`decided_at`/
`decision_note`, sets `status` to `selected` or `rejected`. Still no
separate "decision" entity or approval chain.

## 8. RFQ -> Purchase Order

`POST /api/rfqs/{id}/convert-to-po`: `{warehouse_id, lines?:
[{rfq_line_id, unit_price?}]}`. Only valid from `selected`. Supplier
comes from the selected response's invitation (`invitation.supplier_id`,
re-checked active). Raw materials and quantities still carry forward
automatically from the RFQ's own lines, never re-entered.

`unit_price` per line defaults from the selected response's matching
`RfqResponseLine.unit_price`:

- `lines` omitted — every RFQ line converts at its quoted price.
- `lines` given — exactly those lines convert (a subset is allowed, as
  in v1), each at its `unit_price` override, or the quoted price when
  the override is omitted.
- A line with neither a quote nor an override is rejected (422) naming
  the line — a price is never guessed. The frontend pre-fills the form
  from the quote, so this only asks for what the supplier didn't quote.

`warehouse_id` is still the only field with no upstream source at all.

Implemented by `purchase_order_service.create_purchase_order_with_lines`
— unchanged shared function from v1 — followed by stamping
`Rfq.purchase_order_id` and flipping `Rfq.status` to `converted`, one
transaction (#14). Transition-guard-as-idempotency-guard unchanged.

## 9. Lifecycle

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

Unchanged from v1, plus `cancelled` reachable from `draft`, `issued`,
`response_received`, or `selected`. `draft -> issued` requires at least
one line **and** at least one invitation. Issuing still generates and
sends nothing (#11). `issued -> response_received` happens automatically
off the first captured response, across any invitation. Cancelling still
requires a non-blank reason.

## 10. Numbering

`YY3NNNN`, per-organisation, resets yearly. Unchanged from v1
(`app/services/rfq_service.generate_rfq_number`).

## 11. Issuing — no email, no PDF

Unchanged from v1. "Issue" is a plain status transition, not a
document-generation or communication feature — each invited supplier is
still contacted through whatever channel the business already uses. See
`../audit/RFQ_AUDIT_V2.md` #3.

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
`supplier_id`/`team_id`/`raw_material_id`/`warehouse_id` are validated
active-and-same-organisation on every write. An invitation id is always
resolved within the RFQ in the path. A cross-organisation id anywhere in
this module 404s, never 403s.

## 17. Attachments

Unchanged from v1: the existing generic `files` system,
`entity_type="rfq_response"`, same access-checker registration.

## 18. List and comparison UX

List page (`DataTable`/`FilterBar`/`ActionMenu`/`Badge`): RFQ number,
department (if set), date, priority badge, "Suppliers" (invited count,
and once any have quoted, e.g. "2 of 3 quoted"), status, PO status.
Filters: RFQ number search, priority; the API also filters by `status`,
`team_id`, and `supplier_id` (RFQs that supplier was invited to).

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
