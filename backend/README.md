# Backend

Server-side application: API, authentication, authorization (RBAC),
business rules and database access.

Not yet implemented. When scaffolding this, follow
[`docs/ENGINEERING_PRINCIPLES.md`](../docs/ENGINEERING_PRINCIPLES.md) —
in particular:

- one authentication implementation, one RBAC system (Principle 2)
- every protected endpoint and query enforces access rules server-side
  (Principle 3)
- transactions for multi-step operations, proper constraints and indexes
  (Principle 10)
- explicit states and transitions for business documents (Principle 11)
