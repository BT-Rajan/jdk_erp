# JDK Database + Transaction Integrity

A small, strong reusable foundation for how every table and every
multi-step business operation is built. Not a generic transaction
framework or a distributed-transaction system — the database is the
final authority for data integrity; transactions protect logical
operations; application code handles business behaviour but never
assumes application-level checks alone are sufficient.

## 1. Database rules

- One supported relational database (MySQL).
- Consistent table/column naming with proper auditability and
  traceability.
- Every table has a clear primary key.
- Foreign keys enforced by the database.
- Appropriate `NOT NULL` constraints.
- Appropriate `UNIQUE` constraints.
- Correct `DECIMAL` types for money/quantities.
- Proper date/time storage.
- No business data stored as formatted strings.
- No unnecessary JSON fields where relational columns are appropriate.

## 2. Referential integrity

- Parent/child relationships enforced with foreign keys.
- Define explicit delete behaviour.
- Do not allow deletion that would orphan important business records.
- Prefer deactivation/archiving for business/master records where
  history matters.

## 3. Indexing

- Index foreign keys used in queries.
- Index frequently searched/filtering fields.
- Composite indexes for common multi-column queries.
- Unique indexes for business uniqueness rules.
- Avoid indexing every column.
- Review indexes against actual query patterns.

## 4. Migrations

- All schema changes through versioned migrations.
- Never manually modify production schema.
- Migrations must be repeatable and tracked.
- Destructive schema changes require deliberate migration steps.
- Migration failure must not leave the database in an unknown state
  where possible.

## 5. Transactions

Use transactions whenever multiple database operations represent one
logical business operation.

Example:

```text
Create order
  ↓
Create order lines
  ↓
Update required quantities
  ↓
Create related records
  ↓
Audit transaction
```

Either the complete operation succeeds or it rolls back.

## 6. Transaction rules

- Keep transactions as short as practical.
- Do not perform slow external operations inside a DB transaction.
- Validate before opening the transaction where possible.
- Perform authoritative business changes inside the transaction.
- Commit only after all required database operations succeed.
- Roll back on failure.
- Never pretend a transaction succeeded if commit failed.

## 7. Atomic updates

Prefer database-level atomic operations. For example, avoid:

```text
read stock = 10
application calculates 10 - 3
write stock = 7
```

when concurrent users can modify the same stock. Instead use an
atomic/locked update appropriate to the operation.

## 8. Data integrity belongs to the database too

Do not rely only on application code. Enforce where practical: unique
values, valid relationships, non-null requirements, valid numeric
ranges, valid status relationships where appropriate,
organisation/data-boundary constraints.

Application validation gives good user feedback. Database constraints
provide the final protection.

## 9. Business transaction boundary

Every important operation should have a clearly defined boundary:

```text
Request
  ↓
Validate
  ↓
Authorize
  ↓
Begin transaction
  ↓
Read/lock required records
  ↓
Apply business changes
  ↓
Write audit/event data
  ↓
Commit
  ↓
Return success
```

External actions such as email, QR generation, file processing, etc.
should normally happen after commit or through the background-job
system.

## 10. Audit consistency

For important business actions: business change + audit record should
commit together. If the business operation rolls back, its audit
record should not falsely say that it happened.

## 11. No hidden database behaviour

Avoid triggers, stored procedures, cascades and automatic database
behaviour unless there is a clear reason. The application should have a
clear understanding of where important business logic lives.

## Foundation rule

The database is the final authority for data integrity. Transactions
protect logical operations. Application code handles business
behaviour, but must never assume that application-level checks alone
are sufficient.

## Implementation approach

See `docs/audit/DATABASE_TRANSACTION_INTEGRITY_AUDIT.md` for the full
verdict: what already existed (SQLAlchemy models, Alembic migrations,
foreign keys, the `IntegrityError` → 409 handler, one-commit audit
writes), what was a genuine gap (SQLite silently not enforcing foreign
keys, no explicit `ON DELETE` behaviour anywhere, a pre-existing
`audit_events.action` width drift, a two-commit login/refresh, a
missing index on the login-lockout query), and what's deliberately
deferred because no Sales/Finance/Products/Materials tables exist yet
to exercise money/quantity columns or a multi-table business
transaction.
