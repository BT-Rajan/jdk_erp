# JDK Clean ERP Roadmap

This roadmap defines the build order for JDK ERP. It is a project-wide plan,
alongside [`ENGINEERING_PRINCIPLES.md`](ENGINEERING_PRINCIPLES.md) — the
principles say *how* to build, this says *in what order*.

## The project rule

> Do not move to the next phase merely because screens exist. Move when the
> complete business workflow works end-to-end with correct permissions,
> database integrity and usable UX.

The rule for every phase, without exception:

**Audit → Reuse → Clean → Implement → Integrate → Test → Harden**

Not: *Build new → duplicate existing → patch problems later.*

## Phase 0 — Audit & Freeze

- Audit existing architecture, database, modules, authentication, RBAC and
  shared components.
- Identify duplication, dead code and conflicting implementations.
- Identify what already works and do not rewrite it unnecessarily.
- Establish the Engineering Principles as the development standard.
- Create a clear module/dependency map.

## Phase 1 — Foundation

Build/clean the common foundation first:

- Authentication
- Organisation
- Users
- Teams/departments
- Roles/RBAC
- Permissions/access scope
- Session/security
- Audit trail
- Common API/error handling
- Common UI components
- Common tables/forms/modals/filters
- Common validation
- Date/time/currency/number handling

**Goal:** every future module uses the same foundation.

## Phase 2 — Master Data

Create a reliable single source of truth for:

- Customers
- Suppliers
- Products
- Raw materials
- Units
- Categories
- Machines
- Employees/users
- Warehouses/locations
- BOMs
- External QC agents/labs

Keep master data simple and reusable.

## Phase 3 — Sales

Recommended flow:

```
Customer → Feasibility → Quotation → Approval → Order → Invoice/Payment → Delivery
```

Include:

- Salesman ownership
- Manager's team visibility
- Customer history
- Feasibility checks
- Quotation validity
- Approval
- Order creation
- Invoice workflow
- Payment link/QR
- Delivery readiness

The sales dashboard should show what the salesperson/manager needs to act
on, not just charts.

## Phase 4 — Procurement & Inventory

Flow:

```
Material Requirement → Purchase Order → Receipt → Stock
Stock → Issue/Allocation → Production
```

Also:

- Opening stock
- Stock adjustments
- Transfers where actually required
- Supplier history
- Stock ledger
- Low-stock visibility

Inventory should have **one authoritative stock ledger** rather than
different modules maintaining their own stock numbers.

## Phase 5 — Production

Flow:

```
Order → Production Order → Material Requirement → Allocation → Schedule → Production → QC → Finished Goods
```

Support:

- BOM
- Material allocation
- Machine allocation
- Production scheduling
- Execution
- Production quantities
- Wastage/rejection where required
- QC request
- External QC result
- QC acceptance
- Finished-goods release

Do not make production dependent on unnecessary procurement steps if stock
already exists.

## Phase 6 — Delivery

Flow:

```
Order Ready → Delivery Note → Dispatch → Delivered
```

Delivery should consume the correct finished-goods stock and maintain the
document trail.

## Phase 7 — Finance

Keep it practical rather than attempting to build a full accounting
package initially.

Start with:

```
Quotation → Invoice → Payment → Outstanding
```

Then:

- Payment records
- Payment status
- Receivables
- Customer balance
- Basic finance dashboard
- Invoice/receipt documents
- Payment reconciliation

Expand accounting only when the business actually requires it.

## Phase 8 — Management & Reporting

Once transactional modules are stable:

- Sales overview
- Outstanding payments
- Inventory position
- Production status
- Delivery status
- Procurement status
- Team performance
- Management KPIs
- Exportable reports

Reports should read from the same transactional data, not maintain
duplicate reporting tables unless performance later requires it.

## Phase 9 — Hardening

Before calling JDK production-ready:

- RBAC penetration/access testing
- API authorization testing
- Database integrity testing
- Transaction testing
- Edge cases
- Duplicate submission prevention
- Concurrency checks
- Performance testing
- Large-data testing
- Backup/restore
- Audit verification
- Error handling
- Mobile/responsive verification

## Dependency order

The important part is not building modules in isolation:

```text
FOUNDATION
    ↓
MASTER DATA
    ↓
SALES ───────────────┐
    ↓                │
ORDER                │
    ↓                │
PRODUCTION ← INVENTORY ← PROCUREMENT
    ↓
QC
    ↓
FINISHED GOODS
    ↓
DELIVERY
    ↓
INVOICE / PAYMENT
    ↓
REPORTING
```

The ERP should remain **integrated**, not a collection of separate
applications.
