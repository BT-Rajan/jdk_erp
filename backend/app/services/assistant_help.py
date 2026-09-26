"""How-to guide for the JDK Assistant (app/services/assistant_service.py).

This text is part of the assistant's fixed system prompt: identical for
every user and every request, so the provider can cache it (Claude prompt
caching; DeepSeek's automatic prefix cache). Never interpolate anything
per-user or time-dependent here -- that goes in the user message.

Keep it in step with the real screens: menu names, button labels and
rules below are taken from the app as built. When a screen changes,
change this guide in the same pass."""

HELP_GUIDE = """\
JDK ERP HOW-TO GUIDE

NAVIGATION
- The left sidebar is the only menu. Sections: Dashboard, Sales, Procurement, Inventory, Finance, Settings.
- The home icon next to "JDK ERP" in the header goes to the Dashboard. The bell shows notifications. The
  "Account" menu (top right) has "Sign out".
- Sales: Quotations, Sales Orders.
- Procurement: RFQs, Purchase Orders, Goods Receiving.
- Inventory: Stock Adjustments, Opening Stock, Reconciliation, Finished Goods Stock, Finished Goods Adjustments.
- Finance: Payments.
- Settings: the Master Data pages for everyone -- Categories, Units of Measure, Customers, Suppliers, Products,
  Raw Materials, Production Lines, Machines, Warehouses, Bills of Materials. Admins also see Organisation,
  Users, Email, Documents and Working calendar.
- On the small-screen layout the sidebar opens from the menu (three lines) button in the header.

ROLES AND ACCESS
- Roles: Super Admin, Admin, Manager (a Manager in a team is that team's Department Head), Team Member
  (salesman).
- Sales visibility follows customer ownership: a salesman sees only the customers assigned to them and their
  quotations and orders; a Department Head also sees their team members' customers; Admins see everything.
- Procurement, Finance payments and Inventory actions are separate permission grants set by an Admin (for
  example: view purchase orders, create, approve, send, receive goods; record supplier payments; stock
  adjustments, opening stock, reconciliation). A button a user is not granted is not shown, and the server
  refuses the action anyway.
- Master Data pages can be read by everyone; creating and changing master data is mostly Admin-only.

DOCUMENT NUMBERS
- Every document number is YY + a type digit + a running number that restarts each year:
  3 = RFQ, 4 = Quotation, 5 = Purchase Order, 6 = Sales Order, 7 = supplier payment, 9 = goods receipt.
  Example: 2640012 is quotation number 12 of 2026; 2660003 is sales order 3 of 2026.

WORKING CALENDAR AND DELIVERY DATES (Kuwait time)
- Working days are Sunday to Thursday; Friday and Saturday are non-working. Admins add public holidays in
  Settings > Working calendar.
- The same-day cut-off (default 14:00, set by Admins in Settings > Working calendar): after it, "today" is
  treated as the next working day for delivery purposes.
- A requested delivery date is classified as: same day; within 2 working days; more than 2 working days; or a
  non-working date.

CUSTOMERS (Settings > Customers)
- Create: "New Customer" -- name, contact person, phone, email, address. A salesman's new customer is
  assigned to that salesman automatically.
- Edit: Admin only -- open the row's actions and choose "Edit". Admins also set the customer's payment
  arrangement there: "Payment before delivery", "Payment after delivery" or "Admin-approved payment plan"
  (the plan needs its details written in).
- Reassign to another salesman: "Assign..." -- Admins for any customer; a Department Head within their own
  team.
- Activate / Deactivate: Admin only. Inactive customers cannot be used on new documents.
- Before a Sales Order can be created the customer must have a phone number, an address and a payment
  arrangement.

QUOTATIONS (Sales > Quotations)
- Create: "New Quotation" -- choose the customer, the requested delivery date, then "Add Product" for each
  line (quantity in the product's own unit, unit price) and "Save Quotation". Every quotation starts as a
  draft and is valid for 7 days.
- Prices: each product may have a permitted minimum and maximum selling price. A price outside that range
  (or a product without a range) needs an Admin decision: on the quotation an Admin enters a reason and
  chooses "Approve Prices" or "Reject Prices". Changing the lines later clears that decision.
- Feasibility: when the requested date is the same day or within 2 working days, open the quotation and use
  "Check Feasibility" (later "Re-check Feasibility"). Same day is checked against finished goods stock only;
  within 2 working days also checks raw materials through the product's bill of materials, manufacturing
  lead time and production staff. If the check fails, an Admin decides with a reason: "Approve Exception" or
  "Reject Exception". A non-working requested date always needs an Admin decision on a feasibility check.
  A result goes out of date when the customer, date or lines change, or when the delivery window changes
  over time -- then check again.
- Readiness (shown on the quotation): Ready, Feasibility required, Admin decision required, Price approval
  required, or Not servable, with the reasons listed.
- Edit: the owning salesman edits a draft ("Edit"); once accepted or rejected only an Admin can edit;
  converted quotations are locked for everyone.
- Accept: the owning salesman, on a draft still within its validity -- "Accept".
- Reject: the owning salesman or their Department Head, on a draft -- "Reject", with a mandatory reason.
- Renew: an expired draft can be renewed by its owner -- "Renew" gives it another 7 days.

SALES ORDERS (Sales > Sales Orders)
- Create: open an accepted quotation and choose "Create Sales Order" (the owning salesman only). One
  quotation gives at most one Sales Order; the quotation becomes Converted and is locked.
- Creating the order is refused unless: the customer has a phone number, an address and a payment
  arrangement; and the quotation is Ready -- requested delivery date not in the past, prices in range or
  approved by an Admin, and feasibility current and acceptable when it is needed. Payment does not have to
  be received first.
- The order copies the quotation's customer, products, quantities, prices, totals and requested date, and is
  handed off to fulfilment automatically at once (status "Handed off").
- At hand-off each line is covered from finished goods stock first; any shortfall becomes a production
  requirement for that line.
- Change: Admin only -- "Edit (Admin)", with a mandatory reason. The requested delivery date and prices can
  change; the customer and products never change, and a line's quantity is fixed once it has been assessed
  for fulfilment. Every change is recorded in the history.
- Cancel: Admin only -- "Cancel Order", with a mandatory reason. Cancelling is final.
- "View Quotation" / "View Sales Order" move between the order and its quotation.

REQUESTS FOR QUOTATION -- RFQs (Procurement > RFQs)
- Create: "New RFQ" -- items (raw materials or products with quantities and units), the suppliers to ask,
  priority (normal or urgent), and Required By. Save it as a draft.
- Issue: row action "Edit / Submit..." to submit; then send it to each supplier ("Email" or "Download PDF").
- Record replies: for each supplier either capture their quotation ("Save Quotation": their reference,
  dates, terms, a unit price per item and optional delivery days) or "Mark Declined". Reminders are logged
  with "Save Follow-up".
- Compare the replies side by side on the RFQ, then "Approve or Reject". Approving needs the supplier's
  document attached and confirmation that the agreed quantities equal the requested ones. If the agreed
  quantities differ, use "Raise New RFQ" (the old RFQ is cancelled and a new draft is created).
- Revise a draft or issued RFQ: "Revise...". Cancel: "Cancel RFQ" with a reason.
- After approval: "Generate Purchase Order" / "Create Purchase Order" -- expected delivery date and payment
  terms are required; prices come from the approved quotation and can be edited. "View Purchase Order" opens
  it afterwards.
- RFQ statuses: draft, issued, response received, selected (approved), rejected, cancelled, converted.

PURCHASE ORDERS (Procurement > Purchase Orders)
- Create: "New Purchase" (or generate from an approved RFQ) -- supplier, delivery warehouse, expected
  delivery date (not in the past), payment terms, currency (default KWD), and the items with quantity,
  purchase unit and unit price.
- Submit for approval: "Edit Items / Submit..." -- needs at least one item, expected delivery date, payment
  terms and currency. Status becomes pending approval.
- Approve: "Approve..." (approve permission). "Send Back to Draft" returns it for changes.
- Send: "Send..." -- "Email to Supplier" or "Mark as Sent" if it went another way; "Re-send Email" later.
- Change after approval: "Create Revision" reopens it as a draft; it must be approved again. Each approved
  revision keeps its own document.
- Follow up: "Payments / Follow-up..." -- "Send Follow-up Email" or "Record Supplier Reply"; all shown as a
  timeline on the PO.
- Cancel: "Cancel" with a reason (from draft, pending approval, approved, sent or partially received).
- Statuses: draft, pending approval, approved, sent, partially received, reconciliation required, received,
  payment reconciliation, closed, cancelled. A PO closes automatically once everything is received and the
  payments equal the PO amount.
- Discrepancies: a short delivery puts the PO into reconciliation required, and a payment total different
  from the PO amount puts it into payment reconciliation. The PO's creator resolves it with
  "Resolve Discrepancy..." / "Resolve" -- for example keep the remainder pending, accept the received
  quantity, cancel the remainder, accept the paid amount, or have Finance correct the payment.

GOODS RECEIVING (Procurement > Goods Receiving)
- Lists purchase orders that have been sent and are waiting for goods, with ordered / received / remaining
  quantities.
- Receive: "Receive Goods..." on the PO -- enter the quantity received for each item (in the purchase unit)
  and "Submit Receipt". Posting a receipt adds the stock to the warehouse (in the item's own unit).
- A posted receipt can be reversed with a reason; a draft receipt can be cancelled.

SUPPLIER PAYMENTS (Finance > Payments)
- Lists purchase orders with their amount, status, payment terms and outstanding balance. "Open" a PO and
  fill in the payment (date, amount, method, reference, notes), then "Save Payment". A payment can be marked
  as the final payment.
- Payments can be recorded once the PO is approved, including advance payments before the goods arrive.
- A payment can be cancelled with a reason; a cancelled payment stays visible but no longer counts as paid.
- Recording supplier payments is its own permission grant.

INVENTORY
- Stock Adjustments: "Record Adjustment" -- raw material, warehouse, quantity up or down, and a mandatory
  reason.
- Opening Stock: "Record Opening Stock" -- the one-time verified starting quantity for a raw material in a
  warehouse.
- Reconciliation: compares each raw material's quantity on hand with the sum of its stock movements and
  shows any difference.
- Finished Goods Stock: read-only quantity on hand per product and warehouse.
- Finished Goods Adjustments: "Record Adjustment" -- product, warehouse, quantity up or down, and a
  mandatory reason.
- Stock only moves through these screens and posted goods receipts; the Sales screens never move stock.

MASTER DATA (Settings)
- Products: code, name, category, stock unit, selling price, permitted minimum and maximum selling price,
  manufacturing lead time (days) and production staff needed.
- Raw Materials: code, name, category, unit (and an optional alternate unit conversion).
- Bills of Materials: one per product -- base quantity (in the product's unit) and the raw materials needed.
  A BOM is draft until activated; only an active BOM is used for feasibility and production requirements.
- Units of Measure, Categories, Suppliers, Warehouses, Production Lines and Machines are maintained on
  their own pages.
- Organisation (Admin): company details and production staff available per working day.

WHAT EACH STATUS MEANS
- Quotation: draft (being prepared; can be edited by its salesman, accepted or rejected); accepted (the
  customer agreed; can become a Sales Order); rejected (declined, with the reason recorded); converted (a
  Sales Order was created from it; locked). A draft past its "valid until" date is expired until renewed.
- Quotation price decision: none yet (awaiting an Admin when a price needs approval), approved, rejected.
- Feasibility check: calculated (the check passed or was not needed), Admin decision required, approved by
  Admin, rejected by Admin. It can also be out of date after changes.
- Sales Order: handed off (created and passed to fulfilment -- every new order is handed off at once) or
  cancelled (by an Admin, with the reason recorded).
- Sales Order line fulfilment: from stock (finished goods on hand cover the whole line) or production
  required (the rest needs production). A production requirement is open, or waiting for an active bill of
  materials when the product had none.
- RFQ: draft; issued (sent to suppliers); response received (at least one supplier quoted); selected
  (approved); rejected; cancelled; converted (a purchase order was generated). Each invited supplier's reply
  is sent (awaiting), quoted or declined.
- Purchase Order: draft; pending approval; approved; sent (waiting for delivery); partially received;
  reconciliation required (delivery discrepancy to resolve); received (waiting for payment); payment
  reconciliation (payments differ from the PO amount); closed (fully received and paid); cancelled.
- Goods receipt: draft, posted (stock added), cancelled, reversed (stock taken back out, with a reason).
- Supplier payment: recorded, or cancelled (kept for history, no longer counted as paid).

COMMON QUESTIONS
- "Why can't I create the Sales Order?" -- look at the reason shown: missing customer phone, address or
  payment arrangement (ask an Admin to edit the customer); requested date passed (an Admin edits the
  accepted quotation's date); price approval needed; or feasibility missing, out of date or rejected.
- "Why can't I edit this quotation?" -- after acceptance or rejection only an Admin can; converted
  quotations are locked.
- "Why is Accept missing?" -- the quotation is not a draft, has expired (renew it), or you are not the
  customer's salesman.
- "Why can't I receive goods on this PO?" -- goods are received only on a sent PO, and only with the
  receive permission.
- "Why is my PO stuck in reconciliation?" -- the delivery or payments did not match the PO; its creator
  must resolve the discrepancy.
- "Who can cancel a Sales Order?" -- only an Admin, with a reason.
- "Why can't I see a customer, quotation or order?" -- Sales records are visible only to the customer's
  salesman, their Department Head and Admins. Ask an Admin or your Department Head to reassign the customer
  if it should be yours.
- "Why is a button missing?" -- the action needs a permission you have not been granted, or the record is
  not in a status that allows it (for example a cancelled or converted document).
- "Why does the feasibility check say it's out of date?" -- the quotation's customer, date or lines changed
  after the check, a newer check exists, or the delivery window moved with time (for example after the
  same-day cut-off). Run the check again.
- "How do I change a price on an accepted quotation?" -- only an Admin can edit an accepted quotation; if the
  new price is outside the permitted range, an Admin must also approve the prices again.
- "How much do we still owe a supplier?" -- Finance > Payments shows each PO's outstanding amount; the PO
  itself shows its amount, paid and outstanding.
"""
