"""Action Required (gap-fix): one read-only, aggregated list answering
only "what procurement items require my attention now?" for a Purchase
user. Every item is built from the exact same RfqOut/PurchaseOrderOut
the existing RFQ/PO screens already compute (app/api/rfqs.py's
_build_rfq_outs, app/api/purchase_orders.py's _build_po_out) -- no new
status, no new computation, no notification/reminder/escalation. Each
item's `entity`+`id` is exactly what the existing /rfqs/{id} and
/purchase-orders/{id} screens already take; there is no separate detail
view here. Visible sections are gated by the same rfq_scope.VIEW /
purchase_scope.VIEW the existing RFQ/PO list screens already require --
no new permission."""
from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.finance import _PAYABLE
from app.api.purchase_orders import _build_po_out
from app.api.rfqs import _build_rfq_outs
from app.core.database import get_db
from app.models.purchase_order import (
    CANCELLED,
    CLOSED,
    DRAFT,
    PARTIALLY_RECEIVED,
    PAYMENT_RECONCILIATION,
    PENDING_APPROVAL,
    RECONCILIATION_OPEN,
    RECONCILIATION_REQUIRED,
    PurchaseOrder,
)
from app.models.rfq import INVITATION_SENT, ISSUED, RESPONSE_RECEIVED, Rfq
from app.models.supplier import Supplier
from app.models.user import User
from app.schemas.action_item import (
    ActionItemOut,
    PO_OVERDUE,
    PO_PARTIALLY_RECEIVED,
    PO_PENDING_APPROVAL,
    PO_REQUIRES_PAYMENT,
    PO_REQUIRES_RECONCILIATION,
    RFQ_AWAITING_RESPONSE,
    RFQ_NEEDS_DECISION,
)
from app.services import purchase_scope, rfq_scope

router = APIRouter(prefix="/api/action-items", tags=["action-items"])


def _rfq_items(db: Session, organisation_id: int) -> list[ActionItemOut]:
    rfqs = (
        db.query(Rfq)
        .filter(Rfq.organisation_id == organisation_id, Rfq.status.in_((ISSUED, RESPONSE_RECEIVED)))
        .order_by(Rfq.rfq_date)
        .all()
    )
    if not rfqs:
        return []
    items: list[ActionItemOut] = []
    for rfq_out in _build_rfq_outs(db, rfqs):
        responded = sum(1 for invitation in rfq_out.invitations if invitation.status != INVITATION_SENT)
        total = len(rfq_out.invitations)
        detail = f"{responded}/{total} supplier(s) responded"
        if rfq_out.status == ISSUED:
            items.append(
                ActionItemOut(
                    type=RFQ_AWAITING_RESPONSE,
                    label="Awaiting supplier response",
                    entity="rfq",
                    id=rfq_out.id,
                    reference=rfq_out.rfq_number,
                    supplier_name=None,
                    detail=detail,
                    date=rfq_out.rfq_date,
                )
            )
        else:
            items.append(
                ActionItemOut(
                    type=RFQ_NEEDS_DECISION,
                    label="Supplier response needs a decision",
                    entity="rfq",
                    id=rfq_out.id,
                    reference=rfq_out.rfq_number,
                    supplier_name=None,
                    detail=detail,
                    date=rfq_out.rfq_date,
                )
            )
    return items


def _po_items(db: Session, organisation_id: int) -> list[ActionItemOut]:
    purchase_orders = (
        db.query(PurchaseOrder)
        .filter(
            PurchaseOrder.organisation_id == organisation_id,
            PurchaseOrder.status.notin_((DRAFT, CLOSED, CANCELLED)),
        )
        .order_by(PurchaseOrder.order_date)
        .all()
    )
    if not purchase_orders:
        return []
    supplier_names = dict(
        db.query(Supplier.id, Supplier.name).filter(Supplier.id.in_({po.supplier_id for po in purchase_orders}))
    )

    items: list[ActionItemOut] = []
    for po in purchase_orders:
        po_out = _build_po_out(db, po)
        supplier_name = supplier_names.get(po_out.supplier_id)

        if po_out.status == PENDING_APPROVAL:
            items.append(
                ActionItemOut(
                    type=PO_PENDING_APPROVAL,
                    label="Pending approval",
                    entity="purchase_order",
                    id=po_out.id,
                    reference=po_out.po_number,
                    supplier_name=supplier_name,
                    detail=f"{po_out.total_amount} {po_out.currency}",
                    date=po_out.order_date,
                )
            )
        elif po_out.status == PARTIALLY_RECEIVED:
            short = sum(
                1 for line in po_out.lines if line.received_quantity < line.quantity - line.cancelled_quantity
            )
            items.append(
                ActionItemOut(
                    type=PO_PARTIALLY_RECEIVED,
                    label="Outstanding balance after partial receipt",
                    entity="purchase_order",
                    id=po_out.id,
                    reference=po_out.po_number,
                    supplier_name=supplier_name,
                    detail=f"{short} line(s) short",
                    date=po_out.expected_delivery_date,
                )
            )
        elif po_out.status in (RECONCILIATION_REQUIRED, PAYMENT_RECONCILIATION):
            open_reconciliation = next((r for r in po_out.reconciliations if r.status == RECONCILIATION_OPEN), None)
            items.append(
                ActionItemOut(
                    type=PO_REQUIRES_RECONCILIATION,
                    label="Requires reconciliation",
                    entity="purchase_order",
                    id=po_out.id,
                    reference=po_out.po_number,
                    supplier_name=supplier_name,
                    detail=open_reconciliation.discrepancy if open_reconciliation else None,
                    date=po_out.order_date,
                )
            )

        if po_out.is_overdue:
            items.append(
                ActionItemOut(
                    type=PO_OVERDUE,
                    label="Overdue for delivery",
                    entity="purchase_order",
                    id=po_out.id,
                    reference=po_out.po_number,
                    supplier_name=supplier_name,
                    detail=f"Overdue {po_out.days_overdue} day(s)",
                    date=po_out.expected_delivery_date,
                )
            )
        if po_out.status in _PAYABLE and po_out.outstanding_amount > 0:
            items.append(
                ActionItemOut(
                    type=PO_REQUIRES_PAYMENT,
                    label="Requires payment",
                    entity="purchase_order",
                    id=po_out.id,
                    reference=po_out.po_number,
                    supplier_name=supplier_name,
                    detail=f"{po_out.outstanding_amount} {po_out.currency} outstanding",
                    date=po_out.order_date,
                )
            )
    return items


@router.get("", response_model=list[ActionItemOut])
def list_action_items(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[ActionItemOut]:
    """Shows only the sections this user already has view access to --
    no grant is checked here that the existing RFQ/PO list screens don't
    already require."""
    items: list[ActionItemOut] = []
    if rfq_scope.can_perform(db, current_user, rfq_scope.VIEW):
        items.extend(_rfq_items(db, current_user.organisation_id))
    if purchase_scope.can_perform(db, current_user, purchase_scope.VIEW):
        items.extend(_po_items(db, current_user.organisation_id))
    return items
