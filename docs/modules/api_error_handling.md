# JDK Common API & Error Handling

Eighth foundation layer, after [`audit_trail.md`](audit_trail.md), per
[`../ROADMAP.md`](../ROADMAP.md). A hard platform rule, especially for
an ERP: users get useful business-facing errors; developers get
technical diagnostics through controlled server logs — never through
the browser.

## 1. Single API behaviour

All APIs follow one consistent pattern for: success, validation failure,
authentication failure, authorization failure, not found, conflict,
business-rule failure, and unexpected server error. Every module uses
the same conventions.

## 2. Never expose implementation details

No code, query, stack trace, or internal technical detail may reach the
client. Never expose: SQL queries, SQL errors, stack traces,
source-code paths, filenames/internal class names, framework errors,
database structure, table/column names, server configuration,
environment variables, secrets/tokens, internal service details, or
debugging information. Applies to API responses, UI errors, and browser
console output intended for users. Even on an exception, the user
receives a controlled message.

## 3. Clear professional messages

Messages explain what happened and what the user can do next.

- Good: *"Unable to save the quotation. Please review the required
  fields and try again."*
- Better, when the business reason is known: *"Quotation cannot be
  approved because its validity period has expired."*
- Not: `SQLSTATE[23000]: Integrity constraint violation...`
- Not: `"Something went wrong."` — unless the cause genuinely cannot be
  safely explained.

## 4. Separate user message from technical diagnostic

```text
User action
    ↓
Application error
    ├── User → safe professional message
    └── Server → detailed diagnostic log
```

The server log contains request ID, timestamp, endpoint, authenticated
user, the relevant internal exception, stack trace, and technical
context. The technical information stays on the server.

## 5. Never leak through error status

A database failure never automatically becomes a raw database response.
An unexpected exception becomes a controlled *"Unable to complete this
request at the moment. Please try again."*, with an internal reference
ID where useful (e.g. *"Reference: `REQ-8F42K`."*) so support/developers
can find the real server-side error.

## 6. Standard error categories

```text
VALIDATION_ERROR
AUTHENTICATION_ERROR
ACCESS_DENIED
NOT_FOUND
CONFLICT
BUSINESS_RULE_ERROR
RATE_LIMITED
SERVER_ERROR
```

Don't create hundreds of error types.

## 7. Validation

Validation errors identify the actual problem: *"Customer name is
required."*, *"Quantity must be greater than zero."*, *"This quotation
has already expired."* Return field-level errors where appropriate so
the UI can show them beside the relevant field.

## 8. Authorization errors

Don't reveal sensitive information. If a user attempts to access
another team's record, don't explain the internal authorization rule —
return *"You do not have permission to access this record."*, not *"You
are Team Member of Sales and this record belongs to Accounts."*

## 9. Not found

Use a neutral response: *"The requested record could not be found."*
Don't reveal whether a hidden record exists — especially for customers,
users, financial records, orders, and internal documents.

## 10. Business errors

Specific, professional messages: *"This quotation cannot be converted
because it has expired."*, *"Insufficient finished-goods stock is
available for this order."*, *"This production order cannot be
completed until QC is accepted."*

## 11. Duplicate/conflict errors

*"A customer with this name/code already exists."* or *"This record was
changed by another user. Refresh the page and try again."* Never expose
database uniqueness errors.

## 12. Unexpected errors

User: *"We couldn't complete this request. Please try again."* Server:
full technical diagnostic + request ID. Never show `TypeError...`,
`PDOException...`, `Undefined variable...`, `/var/www/...`, etc.

## 13. API consistency

```text
Success
{
    success: true,
    data: ...
}

Error
{
    success: false,
    error: {
        code: "...",
        message: "...",
        fields: ...
    },
    request_id: "..."
}
```

The exact implementation follows the existing JDK stack after audit —
don't impose a new API framework unnecessarily.

## 14. Frontend behaviour

The UI translates API responses into the standard JDK presentation:
field error → beside field; business error → clear alert/dialog; access
denied → permission message; session expired → controlled
login/session message; server error → professional retry message;
success → concise confirmation. No raw API response is ever dumped onto
the screen.

## 15. Logging

Detailed technical errors belong in controlled server-side logs, with
enough information to diagnose without exposing secrets. Never log
passwords, session cookies, authentication tokens, API keys, or
sensitive payment information.

## 16. Production rule

Development/debug mode must never accidentally expose technical errors
in production:

```text
Development → Detailed server diagnostics
Production  → Safe user message + Server-side diagnostic
```

## Core principle

> Users receive clear, professional, actionable messages. Developers
> receive detailed diagnostics through secure server-side logs. Nothing
> in an API response or UI should reveal source code, database queries,
> internal architecture, paths, secrets or stack traces.

Non-negotiable JDK platform rule, applied to every module — including
all future development.

## Implementation approach

Per [`../ENGINEERING_PRINCIPLES.md`](../ENGINEERING_PRINCIPLES.md) §16
and the roadmap's audit-first rule: see
[`../audit/API_ERROR_HANDLING_AUDIT.md`](../audit/API_ERROR_HANDLING_AUDIT.md).
