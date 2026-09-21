# JDK ERP — Engineering Principles

These are the engineering principles for the JDK ERP. They are **project-wide
rules** for all development on this codebase — every module, every pull
request, every reviewer.

If a proposed change conflicts with one of these principles, the principle
wins unless the team explicitly decides to amend this document first.

## 1. Simple, strong architecture

- Prefer a simple architecture with clear module boundaries.
- Do not introduce complexity unless there is a demonstrated business or
  technical need.
- One application and one database are acceptable; scale the architecture
  only when required.

## 2. One source of truth

- One implementation for authentication.
- One RBAC/access-control system.
- One definition of important business rules.
- One reusable implementation for common functionality.
- Never duplicate logic across modules.

## 3. Server-side authority

- The backend is the final authority for authentication, authorization and
  business rules.
- UI visibility is only a usability feature, not security.
- Every protected API and data query must enforce access rules.

## 4. Clear business boundaries

- Each module owns its own business logic and data responsibilities.
- Avoid cross-module duplication.
- Shared functionality belongs in a common reusable layer.

## 5. Reuse before creating

Before writing new code, check whether an existing:

- component
- service
- API
- validation rule
- database utility
- table/query pattern
- UI pattern

already solves the problem.

**Extend or reuse it rather than creating another version.**

Do not create abstractions merely for theoretical reuse. Reuse should remain
simple and readable.

## 6. Standard UI system

Use a consistent set of standard UI components throughout JDK:

- buttons
- forms
- inputs
- selects
- tables
- filters
- modals/dialogs
- alerts
- confirmation dialogs
- badges/status indicators
- pagination
- loading/empty/error states
- date, currency and number displays

Common components should have **one implementation and one visual
behaviour**.

Do not create slightly different versions of the same component for
individual modules unless there is a genuine requirement.

## 7. Consistent UX

- Same actions should behave the same way throughout the ERP.
- Same terminology should be used everywhere.
- Same status colours, buttons, confirmations and error handling should be
  used consistently.
- Users should not have to relearn the interface for each module.

## 8. Performance by design

Build for good performance from the beginning:

- efficient database queries
- proper indexes
- pagination for large lists
- avoid N+1 queries
- avoid unnecessary API requests
- avoid loading unnecessary data
- use appropriate caching only where it provides measurable benefit
- keep frontend bundles and dependencies under control

Do not sacrifice simplicity for speculative optimisation.

## 9. Scalable without over-engineering

The code should be capable of growing from a small business ERP to a
significantly larger installation without requiring a rewrite.

However:

- no microservices without a real need
- no unnecessary message queues
- no unnecessary caching layers
- no excessive abstraction
- no distributed architecture just for "scalability"

**Scale the implementation, not the complexity.**

## 10. Database integrity

- Use proper relationships and foreign keys where appropriate.
- Use unique constraints where required.
- Use indexes based on actual access patterns.
- Use transactions for multi-step operations.
- Do not rely solely on frontend validation.

## 11. Explicit business states

Documents such as quotations, orders, production orders, invoices and
deliveries must have clearly defined states and valid transitions.

Do not allow arbitrary status manipulation.

## 12. Security and least privilege

- Secure password hashing.
- Secure sessions/tokens.
- Validate all input.
- Enforce authorization server-side.
- Prevent privilege escalation.
- Never trust client-supplied role, user or organisation identifiers.

## 13. Auditability

Important business and security actions should be traceable:

- who
- what changed
- when

Especially for users, roles, approvals, financial documents, stock and
other sensitive operations.

## 14. Test business behaviour

Tests should verify real ERP behaviour and access boundaries rather than
merely testing implementation details.

Examples:

- user cannot access another team's records
- manager can access their team's records
- invalid document transitions are rejected
- stock movements remain consistent
- unauthorized API requests are rejected

## 15. No feature drift

- Do exactly what the business workflow requires.
- Do not add speculative features.
- Do not redesign working modules without a reason.
- Do not change unrelated functionality while implementing a feature.

## 16. Audit before changing

Before modifying an existing area:

1. Inspect the current implementation.
2. Identify reusable code.
3. Identify duplication.
4. Identify dependencies and side effects.
5. Make the smallest clean change required.

Never assume functionality exists without checking the code.

## 17. Maintainability

Code should be:

- readable
- predictable
- modular
- easy to debug
- easy for another developer to understand

Prefer straightforward code over clever code.

## 18. Production principle

Every implementation should satisfy, in this order:

**Correctness → Security → Data integrity → Performance → Maintainability →
Simplicity**

Do not optimize for architectural sophistication.

---

## Golden rule

> Build the simplest architecture that is strong enough for the next stage
> of the business, reuse what already exists, keep one source of truth,
> enforce rules at the server/database level, use standard UI components,
> and make performance a design consideration from the beginning.
