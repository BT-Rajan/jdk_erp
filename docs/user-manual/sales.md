# JDK ERP — Sales (Quotations & Sales Orders)

Reference manual for the Sales module: quoting a customer, getting a
quotation accepted, and converting it into a Sales Order. Each entry
gives the screen path, who can use it, and what it does.

---

## 1. Core model (read this first)

```
Customer (owned by a salesman)
    ↓
Quotation  →  draft → accepted → converted
                  ↘ rejected
    ↓ (convert)
Sales Order  →  handed_off → cancelled
```

- A Quotation and its Sales Order have **no permission of their own** —
  access always comes from who owns the **Customer** they're for
  (Customer's "Assigned To" salesman). See §4.
- **Scope** (from the RBAC model): Admin/Super Admin see **ALL**
  quotations/orders in the org; a Manager sees **TEAM** (their team's
  customers); a Team Member sees **OWN** (only customers assigned to
  them).
- A quotation is valid **7 calendar days** from its quotation date (or
  from the day it's renewed).
- Numbering: quotations `YY4NNNN`, sales orders `YY6NNNN` — assigned
  once, never reused.

### Quotation statuses

| Status | Meaning |
|---|---|
| Draft | Being prepared; only this state can be edited by the salesman, accepted, rejected, or renewed |
| Accepted | Customer accepted it; eligible to convert to a Sales Order |
| Rejected | Final — no path back to draft |
| Converted | Turned into a Sales Order; locked for everyone, no further changes |

### Sales Order statuses

| Status | Meaning |
|---|---|
| Handed off | Every order is this, automatically, the moment it's created from a quotation |
| Cancelled | Final — Admin only, with a reason |

---

## 2. Quotations — screens & transactions

### 2.1 View quotations
- **Navigate:** Sidebar → Sales → Quotations (`/sales/quotations`)
- **Who:** any signed-in user (rows limited to what their scope allows)
- **Shows:** number, customer, date, requested delivery, delivery window, total, status, readiness, created by, last updated
- **Options:** search by quotation number or customer name; **Open** button per row → detail

### 2.2 Create a quotation
- **Navigate:** Quotations → **New Quotation** button (`/sales/quotations/new`)
- **Who:** any signed-in user, for a customer within their own scope (their own customers for a Team Member; their team's for a Manager)
- **Fields:** Customer, Requested Delivery Date, one or more product lines (Product, Quantity, Unit — shown automatically from the product, Unit Price) — **Add Product** / **Remove** per line
- **Does:** server calculates line amounts, subtotal and total; saves as Draft

### 2.3 View a quotation
- **Navigate:** Quotations → **Open** (or the quotation number link) → `/sales/quotations/:id`
- **Shows:** status, valid-until date, customer, quotation date, requested delivery, delivery window, created by, last updated, line items with amounts, subtotal/total
- **Also runs automatically on open:** a fresh **Readiness** check (see §2.6) — not a stored click, re-evaluated every time the page loads

### 2.4 Edit a quotation
- **Navigate:** Quotation detail → **Edit** button → `/sales/quotations/:id/edit` (same form as §2.2)
- **Who:**
  - **Draft** → only the salesman who owns the quotation's customer
  - **Accepted / Rejected** → Admin/Super Admin only
  - **Converted** → no one; locked
- **Does:** re-validates and re-prices every line on the server; changing customer, date or lines makes any earlier feasibility check stale (needs re-running)

### 2.5 Check feasibility
- **Navigate:** Quotation detail → **Feasibility** card → **Check Feasibility** / **Re-check Feasibility** button
- **Who:** anyone who can see the quotation (running a check is not restricted)
- **Does:** calculates now whether the requested delivery is achievable (stock, BOM, lead time, staffing); stores the result as a new record each time — history is kept, not overwritten
- **Possible results:** calculated & servable / not servable / **admin override required** (needs a decision below)

### 2.6 Decide a feasibility exception (Admin)
- **Navigate:** same Feasibility card, appears only when a decision is pending → **Approve Exception** / **Reject Exception**, with a required reason
- **Who:** Admin, Super Admin only
- **Does:** records the decision against that check record; the underlying calculation itself is never altered

### 2.7 Approve/reject quoted prices (Admin)
- **Navigate:** Quotation detail → **Price Approval** card (only appears when a line's price is outside its product's permitted range) → **Approve Prices** / **Reject Prices**, with a required reason
- **Who:** Admin, Super Admin only
- **Does:** unblocks (or blocks) the quotation from being marked Ready; editing the lines afterward clears the decision, requiring a fresh one

### 2.8 Readiness (automatic, not a screen action)
- **Where shown:** Quotation detail → **Readiness** card
- **Does:** combines delivery-window feasibility + any pending Admin decisions (feasibility exception, price approval) into one status: **Ready**, **Feasibility required**, **Admin decision required**, **Price approval required**, or **Not servable**
- Re-evaluated every time the page is opened; nothing is stored as "the" readiness beyond that read

### 2.9 Accept a quotation
- **Navigate:** Quotation detail → **Accept** button
- **Who:** only the salesman who owns the quotation's customer
- **Requires:** status Draft, and still within its 7-day validity
- **Does:** records customer acceptance; makes the quotation eligible to convert (does not create the order itself)

### 2.10 Reject a quotation
- **Navigate:** Quotation detail → **Reject** button → reason (required) → confirm
- **Who:** the owning salesman, or their **team head** (a Manager sharing a team with them)
- **Requires:** status Draft
- **Does:** final — no path back to draft

### 2.11 Renew an expired quotation
- **Navigate:** Quotation detail → **Renew** button (appears only when the draft has passed its valid-until date)
- **Who:** only the owning salesman
- **Does:** restarts the 7-day validity window from today; nothing else changes

### 2.12 Convert to a Sales Order
- **Navigate:** Quotation detail → **Create Sales Order** button
- **Who:** only the salesman who owns the quotation's customer
- **Requires:** status Accepted
- **Does:** creates the Sales Order (automatically handed off to fulfilment on creation), locks the quotation as Converted; a **View Sales Order** button then replaces it on the detail page

---

## 3. Sales Orders — screens & transactions

There is **no "create order" screen** — every Sales Order comes only from converting an accepted quotation (§2.12).

### 3.1 View sales orders
- **Navigate:** Sidebar → Sales → Sales Orders (`/sales/orders`)
- **Who:** any signed-in user (rows limited by the same customer-based scope as quotations)
- **Shows:** order number, customer, date, requested delivery, total, status
- **Options:** search by order number or customer name; **Open** button per row → detail

### 3.2 View a sales order
- **Navigate:** Sales Orders → **Open** → `/sales/orders/:id`
- **Shows:** status, customer, source quotation (link via **View Quotation**), order date, requested delivery, when/how it was handed off, last updated, line items with amounts, subtotal/total

### 3.3 Edit a sales order (Admin)
- **Navigate:** Sales Order detail → **Edit (Admin)** button
- **Who:** Admin, Super Admin only
- **Fields:** requested delivery date, line quantities/prices, plus a required **reason for the change**
- **Not editable:** the customer, products or units on an order — those are locked
- **Does:** re-validates and re-prices on the server; every change audited with old → new value

### 3.4 Cancel a sales order (Admin)
- **Navigate:** Sales Order detail → **Cancel Order** button → reason (required) → confirm (or **Keep Order** to back out)
- **Who:** Admin, Super Admin only
- **Does:** final — no path back

---

## 4. Customer ownership (why access is scoped the way it is)

- **Navigate:** Master Data → Customers (`/customers`) → row's **Assign** action
- **Who can assign/reassign:** Admin, Super Admin, or a Manager assigning within a team they're part of (a "department head" move — Manager can only assign to someone sharing a team with them)
- **Does:** sets the customer's **Assigned To** salesman — this one field is what determines who can see and act on every quotation and sales order for that customer. There is no separate Sales-specific permission to configure.

---

## 5. Capabilities without a screen yet

Exist as backend endpoints, not exposed as a distinct screen/section
today — so a downstream assistant shouldn't describe a UI for these:

| Capability | Notes |
|---|---|
| Raw feasibility calculation (`GET .../feasibility`) | Read-only day-count calculation; the UI only shows the *saved* feasibility-check records (§2.5), not this live calculation directly |
| Same-day finished-goods gate (`GET .../same-day-fg`) | Read-only; folded into readiness (§2.8), no standalone view |
| Sales Order line fulfilment (`GET .../fulfilment`) | Per-line stock/production coverage after hand-off; no display on the Sales Order screen yet |

---

## 6. What gets audit-logged

- Quotation: created, updated, price decided, accepted, rejected, renewed, converted, readiness assessed
- Feasibility: check recorded, exception decided
- Sales Order: created, updated, cancelled, handed off

---

## 7. Quick answers

- **"Why can't I edit this quotation?"** → it's Accepted/Rejected (Admin-only now) or Converted (locked for everyone); if Draft, only the owning salesman can edit it.
- **"Why is my quotation stuck at 'Admin decision required'?"** → either a feasibility exception or a price is outside range — an Admin needs to approve/reject it on the quotation's detail page.
- **"Can I create a Sales Order directly?"** → no — it only comes from converting an Accepted quotation.
- **"Who can reject a quotation besides the salesman?"** → their team head only (a Manager who shares a team with them), and only while it's still a Draft.
- **"Can a salesman edit an order after it's handed off?"** → no — only Admin/Super Admin, and only with a reason.
- **"Why can't I see a customer/quotation a colleague has?"** → your scope (OWN/TEAM/ALL) is based on who that customer is assigned to — see §4.
