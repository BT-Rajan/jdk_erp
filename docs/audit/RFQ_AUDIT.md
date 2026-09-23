# RFQ (Request for Quotation) — Audit of jdk_clean

Audited before building `docs/modules/rfq.md`, per Principle 5 (reuse
before creating) and Principle 16 (audit before changing). Scope: does
jdk_clean have any "ask a supplier for pricing before committing to a
Purchase Order" concept, and what existing jdk_erp infrastructure (file
attachments, status-transition conventions, document numbering, PO
creation) can this module reuse.

## 1. Does an RFQ concept exist in jdk_clean?

**No — confirmed absent, not merely unsearched.** jdk_clean's own code
comments say so explicitly: `customer.py`'s docstring states this app
has "no purchase-RFQ workflow" and "no RFQ documents," in the context of
explaining why a `customers.group_rfq` boolean column is dead data with
zero downstream behaviour. A full case-insensitive grep across the whole
backend and frontend for `rfq`, `request_for_quotation`,
`quotation_request`, `supplier_quote`, `price_request`, `enquiry`,
`inquiry` returns nothing else. jdk_clean's only `Quotation` entity is
the **sales-side** document (company → customer, `Feasibility ->
Quotation -> Order`) — the reverse commercial direction from a
procurement RFQ (company → supplier). Purchase Orders in jdk_clean are
always created directly by a person, with unit price/quantity/delivery
entered by hand — there is no upstream "what did the supplier quote"
record feeding them. **Decision: build RFQ from this module's own spec
and jdk_erp's own established conventions — there is nothing to adapt
from jdk_clean here**, the same situation Warehouse's audit found for
that module.

## 2. Numbering — YY3NNNN

jdk_clean's `number_series_service.py` is a flat prefix + zero-padded-
integer scheme (`PO-00001`, `QTN-00001`) with no year component and no
RFQ entry in its seed data at all. It doesn't support the required
`YY3NNNN` shape (2-digit year + a fixed document-type digit + a
4-digit **yearly** sequence) regardless. jdk_erp's own `IdFormat`
primitive (`app/core/id_formats.py`) is a fixed prefix + fixed digit
count with no year-scoping either — forcing a year-reset sequence into
that shape would distort a primitive every other master/document in this
codebase already relies on having one simple meaning. **Decision: a
small, dedicated generator** (`app/services/rfq_service.py`'s
`generate_rfq_number`), following the exact same discipline every other
code generator in this codebase already uses (count existing rows
matching this year's prefix, +1, retried against the unique constraint
under `IntegrityError`) — not a new *mechanism*, the same one, just
scoped by year because this one document type's own numbering rule
requires it.

## 3. Supplier response capture

Does not exist in jdk_clean — no structured per-line supplier response
table, no attachment-based "upload the supplier's quote" flow anywhere.
Nothing to reuse or diverge from; built fresh per this module's own spec
(attachment-first, minimal metadata — `docs/modules/rfq.md` #5).

## 4. State/status lifecycle

No RFQ lifecycle exists to reuse. For pattern reference: both
`PurchaseOrder` and the sales-side `Quotation` use an
`ALLOWED_TRANSITIONS` dict + an `assert_transition_allowed` helper,
enforced server-side, never a bare status column. jdk_erp's own
`purchase_order.py`/`purchase_order_service.py` (this codebase's own,
already built in this session) already established the identical
pattern independently. **Decision: reuse jdk_erp's own
`ALLOWED_STATUS_TRANSITIONS` + `assert_transition_allowed` shape** for
RFQ's lifecycle, the same convention now used twice.

One more real, instructive precedent from jdk_clean: a migration named
`2026-10-09_remove_quotation_sent_status.sql` removed a `sent` status
from the sales Quotation, with the comment "a quotation stays 'draft'
(open) until the customer's answer is recorded" — i.e. jdk_clean's own
history independently reached the same "don't add a `sent` status with
no distinct business meaning" conclusion this project's Purchase Order
module already reached (`docs/audit/PROCUREMENT_AUDIT.md` #6). RFQ's
`issued` status here is different in kind, not the same mistake:
`draft -> issued` genuinely marks "we have actually asked the supplier"
(a real fact, whatever channel it went out through), not a decoration
around the next real state.

## 5. Conversion into a Purchase Order

No RFQ->PO conversion exists (there's no RFQ to convert from). The
closest real precedent is jdk_clean's own `create_order_from_quotation`
(sales side): copy every applicable field forward onto the new document,
stamp a back-reference id onto the source, flip the source to a terminal
`converted` status — all in one transaction. **Decision: reuse this
shape** for RFQ -> Purchase Order: `RfqLine.raw_material_id`/`quantity`
copy forward verbatim (no re-entry), the resulting `PurchaseOrder` is
built through this session's own `purchase_order_service` (extracted
into a shared `create_purchase_order_with_lines` function so the plain
"New Purchase" flow and this conversion share one implementation, per
Principle 2), `Rfq.purchase_order_id` stamps the back-reference, and
`Rfq.status` flips to `converted`.

## 6. File/attachment storage

jdk_clean has **no generic polymorphic attachment table** — its real
pattern is a shared *service* (`id_document_service.py`) plus a
dedicated `<entity>_filename` column added to each entity's own table
(Customer, Supplier, QcRequest each do this individually), with no
size/content-type/uploaded-by persisted at all. jdk_erp already has
something strictly better already built in an earlier phase: a real
generic `files` table (`app/models/file.py`) with `entity_type`/
`entity_id`, full metadata (mime type, size, uploader, status), content-
signature validation, and a pluggable per-entity-type access-check
registry (`app/core/entity_access.py`) documented as existing "for the
first module that needs it." **Decision: RFQ is that first module** —
response attachments are plain rows in the existing `files` table
(`entity_type="rfq_response"`), with an access checker registered for
it, never a new attachment mechanism and never a dedicated filename
column on a business table (jdk_clean's own, less capable pattern).

## 7. Permissions

No RFQ page exists in jdk_clean to gate. jdk_clean's own general shape
(`PAGE_KEYS`/`DepartmentPermission`, per-page read/write) is the same
one `docs/audit/PROCUREMENT_AUDIT.md` #11 already found for Purchase
Orders and already declined to reuse in favour of jdk_erp's own
`module_key`/`action`/`scope` permission engine. **Decision: RFQ reuses
that same engine**, `module_key="rfq"`, actions `view`/`create`/`issue`/
`capture_response`/`decide`/`convert` — mirroring Purchase's own
already-established four-action shape, extended by the extra lifecycle
steps this document actually has. Admin always bypasses; no `OWN`/`TEAM`
scope, for the identical reason Purchase Orders have none
(`docs/audit/PROCUREMENT_AUDIT.md` #11) — no ownership/assignment
dimension is evidenced for RFQs either.

## 8. Multiple suppliers per RFQ

No evidence either way in jdk_clean (nothing exists to check). The
task's own spec is explicit that a vendor-bidding/comparison system must
not be built without proof, and every one of its own examples (RFQ
detail page, numbering, "the RFQ represents: we are asking THIS supplier
to quote") frames an RFQ around exactly one supplier. **Decision: one
RFQ = one supplier** (the same one-supplier-per-document shape already
chosen for Purchase Order), with multiple `RfqResponse` rows supported
per RFQ purely to capture that one supplier sending an updated/revised
quote over time — never a different supplier being compared within the
same RFQ. If JDK's real process later proves a genuine multi-supplier
comparison need, that's a new RFQ per supplier today (cheap, no data
loss) until evidence justifies more.

## Bottom line

jdk_clean has zero RFQ prior art of any kind — this module is built
fresh, directly from its own spec, reusing only jdk_erp's own existing
foundations: the generic `files`/`entity_access` attachment system (its
first real consumer), the `ALLOWED_*_TRANSITIONS` status-machine
convention this session's own Purchase Order module just established,
the `authorization_service` permission engine (Purchase's second real
consumer), and a shared, extracted `purchase_order_service` PO-creation
function reused by both the plain create flow and RFQ conversion. The
one genuinely new piece is RFQ's own small year-scoped number generator,
required by the task's explicit `YY3NNNN` format.
