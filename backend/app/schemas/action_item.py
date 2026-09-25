from datetime import date

from pydantic import BaseModel

# One entry per existing, already-actionable RFQ/PO state named in
# docs/modules/rfq.md and docs/modules/purchase_orders.md -- never a new
# status of its own, just a label for an existing one (gap-fix: Action
# Required view).
RFQ_AWAITING_RESPONSE = "rfq_awaiting_response"
RFQ_NEEDS_DECISION = "rfq_needs_decision"
PO_PENDING_APPROVAL = "po_pending_approval"
PO_REQUIRES_PAYMENT = "po_requires_payment"
PO_OVERDUE = "po_overdue"
PO_REQUIRES_RECONCILIATION = "po_requires_reconciliation"
PO_PARTIALLY_RECEIVED = "po_partially_received"


class ActionItemOut(BaseModel):
    """One row of "what needs my attention now" -- assembled entirely
    from each RFQ/PO's own existing status and already-computed fields
    (RfqOut/PurchaseOrderOut), never a new computation of its own. `entity`
    + `id` is exactly what the existing /rfqs/{id} and /purchase-orders/{id}
    screens already take -- there is no separate detail view here."""

    type: str
    label: str
    entity: str  # "rfq" | "purchase_order"
    id: int
    reference: str
    supplier_name: str | None
    detail: str | None
    date: date | None
