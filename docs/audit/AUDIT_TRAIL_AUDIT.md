# Audit Trail Audit — `jdk_clean`

Phase 0 audit of the audit-trail layer, per
[`../ROADMAP.md`](../ROADMAP.md) and the spec in
[`../modules/audit_trail.md`](../modules/audit_trail.md). `jdk_clean` has
two fully separate systems relevant here: a generic business-record
`audit_log` (audited in depth for the first time below), and the
security side, which the authentication audit already established is a
complete blank slate (no login/logout/security-event audit exists in
`jdk_clean` at all).

## Verdict

**Reuse the field-level, append-only, transactionally-coupled design
principles. Do not reuse: the one-row-per-field storage shape, the
duplicated diffing logic, the unpaginated per-record history read, or
the placeholder-string treatment of collection changes.** Unify this
project's own `AuthEvent` (built in the session/security phase, and
already exactly a "Security" audit trail per
[`audit_trail.md`](../modules/audit_trail.md) §2) into one generalized
`AuditEvent` rather than keeping two parallel event tables — the spec's
own example UI mixes a sales approval, a role change, and a stock
adjustment in one list, which only makes sense with one underlying
table.

## What `jdk_clean` got right, reused in shape

- **`audit_log`** (`schema.sql:23-35`): `table_name` + numeric `record_id`
  + `action` + optional `field_name`/`old_value`/`new_value` + nullable
  `changed_by` ("nullable for system actions") + `changed_at`, indexed on
  `(table_name, record_id)` and `changed_at`. The actor-nullable-for-system
  convention, the field-level id-not-code entity key, and the indexing
  shape all carry forward.
- **Only changed fields are ever written** — `log_update` drops
  `updated_at`/`created_at` and any field where `old == new`
  (`audit_service.py:9,42`) — so a save that only bumps a timestamp
  produces zero audit rows. Kept.
- **Entity identity is always a table name + numeric id, never a
  human-readable code** — confirmed with zero exceptions across 30+ call
  sites. A quotation's audit rows key on `quotations`+`123`, not
  `QTN-1024` (the code only ever appears inside a free-text value, e.g.
  `order_service.py:1204`). Kept: `entity_type` + numeric `entity_id`.
- **The audit write is transactionally coupled to the business write**,
  not fire-and-forget — verified by `jdk_clean`'s own test
  (`tests/test_delivery_hardening.py:104-118`), which asserts that a
  failing audit write rolls back the business change too. This is
  exactly [`audit_trail.md`](../modules/audit_trail.md) §12's principle,
  and it's kept: the new `audit_service.log_event()` does not commit —
  the caller commits both the business change and the audit row
  together, same as `jdk_clean`'s pattern.
- **`changed_by IS NULL` for system-initiated actions** (an automatic
  overdue-payment job, an automatic expiry) rather than a fake "system
  user" row (`order_service.py:1601-1603`, `feasibility_service.py:87`).
  Kept — `AuditEvent.actor_user_id` stays nullable for the same reason.

## What's not reused, and why

- **One row per changed field.** `log_update` inserts a separate row per
  field (`audit_service.py:46-51`). This project's `AuditEvent` is one
  row per *event*, with a compact `details` string holding whatever
  field-level changes matter (§5's "Role: Manager → Team Member" is one
  readable line, not N rows) — simpler, and avoids the exact volume risk
  found below.
- **`get_history` has no pagination** (`audit_service.py:82-89`) — a
  single long-lived, heavily-revised record's full trail is returned
  unbounded, unlike the same file's `get_my_history`, which deliberately
  caps at `LIMIT 500` and one month (`audit_service.py:139-141`). §10
  requires pagination everywhere; the new read API always paginates, no
  exceptions.
- **Diffing logic duplicated across 6+ call sites** instead of a shared
  helper (`crud/base.py:105-111` and near-identical loops re-implemented
  in `order_service.py`, `quotation_service.py`,
  `purchase_order_service.py`, `delivery_note_service.py`, ...). A
  `diff_fields()` helper is added to `audit_service` now, even with no
  business module yet to call it, because — unlike a query-scoping
  helper that needs a concrete table's columns to validate against
  (see [`PERMISSIONS_AUDIT.md`](PERMISSIONS_AUDIT.md)) — this is pure
  dict-diffing logic, fully testable in isolation, and the exact
  duplication `jdk_clean` fell into is worth foreclosing before the
  first business module (Phase 2) gets a chance to repeat it.
- **Collection/line changes recorded as placeholder strings**
  (`"3 line(s)" -> "5 line(s)"`, `child_lines.py:117`) instead of a real
  diff — not something to reproduce; left as a documented open question
  for whichever future module first has line-level records to audit.
- **No structural sensitive-field redaction** — the one redacted
  password-reset entry (`app/api/users.py:136-139` in `jdk_clean`) is
  hand-written, with nothing stopping a future call from writing a real
  secret's value into `old_value`/`new_value`. Not a problem yet in this
  project (nothing calls `audit_service.log_event` with a password or
  token value), but worth naming as a rule for every future caller: never
  pass a secret into `details`.
- **No admin-facing cross-entity audit browser at all** — every read in
  `jdk_clean` requires already knowing a `(table_name, record_id)`, or
  being the actor asking about their own last month. This project builds
  a real filterable, paginated `GET /api/audit-events` from the start.

## This project's own security-event side

`AuthEvent` (built during the session/security phase) already covers
exactly [`audit_trail.md`](../modules/audit_trail.md) §2's "Security"
category — login success/failure, logout, password change, role change,
team membership change — with an actor/subject distinction
(`actor_user_id`) `jdk_clean` never had at all for these events (it has
no security audit trail whatsoever, confirmed in
[`AUTHENTICATION_AUDIT.md`](AUTHENTICATION_AUDIT.md) and re-confirmed
here). Generalizing it in place (rename to `AuditEvent`, add
`organisation_id`/`module`/`entity_type`/`entity_id`/`result`/`details`)
is less work and less risk than building a second, parallel table and
reconciling the two later once a real business module needs the unified
view.
