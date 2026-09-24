# RFQ v2 — Audit of v1 and what changed

Audited before revising `docs/modules/rfq.md` (v2), per Principle 16
(audit before changing). Scope: where the v1 RFQ module (`RFQ_AUDIT.md`,
migration `0028`) fell short in real use, what v2 changes to fix that,
and what deliberately stays exactly as v1 built it.

## 1. What was wrong with v1

**One RFQ = one supplier.** v1 (`RFQ_AUDIT.md` #8) put an immutable
`supplier_id` on the RFQ header. Asking three suppliers for the same
materials meant three RFQs with three copies of the same lines, and
nothing in the system tied them together. The v1 audit itself flagged
this as "a new RFQ per supplier today (cheap, no data loss) until
evidence justifies more". That evidence is now in: the business asks
several suppliers for the same request as a matter of routine.

**Responses were files only.** v1 captured a response as an
`RfqResponse` row plus required attachments, with no structured price
(`rfq.md` v1 #5: "the attached document *is* the record"). So:

- nobody could compare suppliers without opening each PDF side by side;
- conversion to a PO asked for every unit price again, even though the
  price was sitting in the attached quote (v1 `rfq.md` #8). That is the
  kind of re-entry the RFQ -> PO flow exists to remove.

**No requesting context.** v1 had no record of who asked for the RFQ,
which department it was for, or how urgent it was.

## 2. What v2 changes

| Area | v1 | v2 | Why |
|---|---|---|---|
| Supplier | `rfqs.supplier_id` (immutable) | `rfq_supplier_invitations` join rows, `UniqueConstraint(rfq_id, supplier_id)` | One request, several suppliers asked. Still a plain join row: no bidding rounds, scoring or procurement-event entity. |
| Response owner | `rfq_responses.rfq_id` | `rfq_responses.invitation_id` | A response always comes from exactly one invited supplier. |
| Response content | note + required files | quotation ref/date, valid-until, payment/delivery/freight terms, note, **`rfq_response_lines`** (`unit_price`, `delivery_days`, `remarks`) + *optional* files | Gives structured data that can be compared and used to pre-fill the PO. Files remain as supporting evidence. |
| Comparison | none | read-only table built from `GET /api/rfqs/{id}` | The question the record exists to answer. No computed ranking or "best" flag. |
| Convert-to-PO | every `unit_price` typed by hand | defaults from the selected response, overridable per line | Removes re-entry. Override is kept because a price agreed verbally doesn't have to match the written quote. |
| Header | — | `team_id` (existing `teams`), `requested_by_user_id` (session-stamped), `priority` (`normal`/`urgent`, display only) | Records who asked and for which department, and lets urgent RFQs be filtered. `teams` is reused as the department; no second department concept is added. |
| Line | — | `remarks` | Grade/size/quality notes that belong on the request itself. Not a price. |
| Issue guard | ≥ 1 line | ≥ 1 line **and** ≥ 1 invitation | An RFQ with nobody invited has nothing to issue. |

New invitation actions:

- `POST/DELETE /api/rfqs/{id}/invitations[/{invitation_id}]`: draft
  only, under the `create` permission, because invitations are part of
  the draft.
- `POST .../invitations/{invitation_id}/decline`: sets a flag only.
  It uses the `capture_response` permission because, like a captured
  response, it records what a supplier answered.

## 3. What stays exactly as v1 built it

- **No email, no PDF** (v1 `rfq.md` #4/#20). "Issue" is still a status
  fact. Inviting several suppliers doesn't change this: each supplier is
  still contacted through whatever channel the business already uses.
- **Lifecycle** and its transition table, including `response_received`
  as a side effect only, the explicit decide action, and transition
  guard = idempotency guard on convert.
- **`YY3NNNN` numbering**, reset yearly, per organisation.
- **Historical integrity.** An RFQ line's quantity is never rewritten.
  A response and its lines are never edited, and a revised quote is a
  new response on the same invitation.
- **Inventory boundary.** Nothing in this module writes stock.
- **Permissions.** Same `module_key="rfq"` and the same six actions. No
  new permission is added.
- **Organisation isolation.** New tables are children of scoped parents
  and have no `organisation_id` of their own, the same shape as
  `rfq_lines`. Cross-organisation ids return 404. A response line that
  points at another RFQ's line is rejected.
- **Attachments** use the existing generic `files` system with
  `entity_type="rfq_response"` and the same access checker.
- **PO creation** still goes through
  `purchase_order_service.create_purchase_order_with_lines`.

## 4. Migration (`0032`)

Every existing v1 row is carried forward and none is dropped:

1. Each RFQ's `supplier_id` becomes one invitation: `quoted` if the RFQ
   already had a response, otherwise `sent`.
2. Each `rfq_responses` row is re-pointed from `rfq_id` to that
   invitation. `rfqs.selected_response_id` stays valid unchanged.
3. `rfqs.supplier_id` and `rfq_responses.rfq_id` are then dropped.
4. v1 responses have no response lines. A v1 RFQ that was `selected` but
   not yet converted still converts, with each price entered by hand as
   in v1, because a line with no quote has no default.

The downgrade refuses to run if any RFQ doesn't have exactly one
invitation, because v1's single `supplier_id` can't represent that. It
refuses instead of quietly dropping suppliers and their responses.

## 5. Performance note

v1 built each list row with per-row queries (lines, responses, files per
response). v2 nests one level deeper, so that pattern would have grown.
`_build_rfq_outs` now loads any page of RFQs in a fixed five queries
(RFQs' lines, invitations, responses, response lines, files), all keyed
by ids that are already organisation-scoped.
