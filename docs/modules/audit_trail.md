# JDK Audit Trail

Seventh foundation layer, after
[`session_security.md`](session_security.md), per
[`../ROADMAP.md`](../ROADMAP.md). Records important business and
security events — not every database operation. Keeps it useful, fast,
and manageable.

## 1. Purpose

Audit answers: who did what, to which record, and when? Primarily for
traceability and accountability, not a second copy of the database.

## 2. What should be audited

- **Security**: login success/failure, logout, password change/reset,
  user activation/deactivation, role change, team membership change.
- **Master data**: create, important edits, deactivation.
- **Business transactions**: quotation created/edited/approved/rejected,
  order created/changed/cancelled, production order changes, stock
  adjustments, QC result/approval, invoice changes, payment status
  changes, delivery/dispatch.
- **Administrative actions**: organisation changes, user changes, team
  changes, permission/access changes.

Don't automatically audit every read/view operation.

## 3. Audit record

```text
Audit Event
 ├── ID
 ├── Organisation ID
 ├── User ID
 ├── Action
 ├── Module
 ├── Entity type
 ├── Entity ID
 ├── Timestamp
 ├── Result
 └── Details
```

Optional technical context where useful: IP address, user agent/request
identifier. Don't store unnecessary personal or sensitive information.

## 4. Example

```text
User: Ravi
Action: APPROVED
Module: Sales
Entity: Quotation
Entity ID: QTN-1024
Time: 21-Sep-2026 14:32
```

```text
User: Admin
Action: TEAM_CHANGED
User: Ravi
From: Sales
To: Accounts
```

A useful history without duplicating the entire record.

## 5. Before/after values

For important changes, capture the relevant change (`Role: Manager →
Team Member`, `Team: Sales → Accounts`). For important business
documents, record the changed fields where useful. Never blindly store
the entire row before and after every update.

## 6. Immutable audit history

Normal users cannot edit or delete audit records, or change the recorded
timestamp, user, or action. Even Admin should not casually modify
historical audit records — a correction creates a new audit event.

## 7. Organisation isolation

Audit records respect the organisation boundary — no organisation's
users can inspect another organisation's audit trail.

## 8. Who can view it?

- **Super Admin**: system-wide audit where applicable.
- **Admin**: organisation audit.
- **Manager**: only relevant team/business events if required.
- **Team Member**: normally no audit administration access.

Don't automatically expose the entire audit history to every manager.

## 9. UI

A simple Audit Trail screen with filters (date, user, module, action,
entity), a standard table, and a detail drawer/modal showing who, when,
action, module, record, and changes. Standard JDK table, filters,
pagination.

## 10. Performance

Append-only writes, proper indexes, pagination, never load the entire
audit table, don't join huge transactional datasets unnecessarily, keep
the payload compact, consider archival later if volume becomes
significant. Useful indexes typically combine `organisation_id`,
`user_id`, `entity_type + entity_id`, `timestamp`, `module + timestamp`.
Don't prematurely build a separate analytics/logging infrastructure.

## 11. Audit vs application logs

Keep them separate. Audit trail: a business/security event that must be
traceable ("Quotation QTN-1024 approved by Ravi"). Application log:
technical information for diagnosing software behaviour ("SQL query took
420ms"). They serve different purposes.

## 12. Transaction principle

The business transaction and its audit event succeed together (approve
→ update → write audit event → commit). If the business transaction
fails, there must be no audit record claiming it succeeded.

## 13. Acceptance tests

1. Important create/change/approve actions generate audit events.
2. Login/security events are recorded appropriately.
3. Audit identifies who, what, when and which record.
4. Important changes show meaningful before/after information.
5. Normal users cannot modify audit history.
6. Audit respects organisation boundaries.
7. Audit list supports filtering and pagination.
8. Audit does not expose passwords, tokens or other secrets.
9. Business transaction and corresponding audit event remain consistent.
10. Audit does not materially slow normal ERP operations.

## Principle to lock in

> Audit important events, keep the history immutable, make it
> searchable, preserve business accountability, and never turn the audit
> system into a duplicate database.

## Foundation so far

```text
Authentication → Organisation → Users → Teams → RBAC →
Session/Security → Audit Trail
```

Next: shared application foundation/UI components, since every actual
ERP module depends on those.

## Implementation approach

Per [`../ENGINEERING_PRINCIPLES.md`](../ENGINEERING_PRINCIPLES.md) §16
and the roadmap's audit-first rule: see
[`../audit/AUDIT_TRAIL_AUDIT.md`](../audit/AUDIT_TRAIL_AUDIT.md).
