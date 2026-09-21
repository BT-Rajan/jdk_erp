# Contributing

## Before you write code

1. Read [`docs/ENGINEERING_PRINCIPLES.md`](docs/ENGINEERING_PRINCIPLES.md).
   It is not optional guidance — it is the standard every change is
   reviewed against.
2. Audit before changing: inspect the current implementation, identify
   reusable code and duplication, and understand dependencies and side
   effects before touching an existing area (Principle 16).
3. Check for an existing component, service, API, validation rule,
   database utility or UI pattern that already solves the problem. Reuse
   or extend it rather than writing a new version (Principle 5).

## While you write code

- Keep the change scoped to the business workflow it implements. No
  speculative features, no unrelated refactors, no drive-by redesigns
  (Principle 15).
- Enforce every access rule and business rule server-side. Never rely on
  the UI to hide something that the API still allows (Principle 3, 12).
- Use the standard UI components for buttons, forms, tables, filters,
  modals, alerts, badges, pagination and loading/empty/error states. Do
  not create a one-off variant for a single module (Principle 6, 7).
- Use transactions for multi-step database operations, and add indexes and
  constraints based on real access patterns (Principle 10).
- Give business documents (quotations, orders, invoices, etc.) explicit
  states and valid transitions — no arbitrary status changes
  (Principle 11).
- Record who did what and when for sensitive operations: user/role
  management, approvals, financial documents, stock movements
  (Principle 13).

## Tests

Tests should verify ERP behaviour and access boundaries, not just
implementation details — for example: a salesman cannot see another
salesman's customers, an invalid quotation transition is rejected, an
unauthorized API request is denied (Principle 14).

## Pull requests

- Describe the business workflow the change implements.
- Call out any reuse decisions (what you extended vs. what you added).
- Confirm server-side enforcement for any new protected endpoint or query.
