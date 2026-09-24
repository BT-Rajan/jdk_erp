"""Finance / Accounts: purchase orders for payment (docs/modules/purchase_orders.md
Revision 8).

Every approved PO comes here, whatever its payment terms -- whether it
is paid before or after delivery is decided case by case. Prepaid POs
come too, so Finance records the payment already made. Finance sees the
PO read-only and records payments through the existing
POST /api/purchase-orders/{id}/payments. Gated by
`purchase_payment:create` alone, so a Finance user needs no Procurement
grant."""

from decimal import Decimal
from math import ceil

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.errors import NotFoundError
from app.core.search import apply_keyword_filter
from app.models.purchase_order import (
    APPROVED,
    CLOSED,
    PARTIALLY_RECEIVED,
    PAYMENT_RECONCILIATION,
    RECEIVED,
    RECONCILIATION_REQUIRED,
    SENT,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderPayment,
)
from app.models.raw_material import RawMaterial
from app.models.rfq import Rfq
from app.models.supplier import Supplier
from app.models.unit import UnitOfMeasure
from app.models.user import User
from app.schemas.pagination import PaginatedResponse, PaginationMeta
from app.schemas.purchase_order import FinanceLineOut, FinancePaymentOut, FinancePurchaseOrderOut
from app.services import purchase_order_service, purchase_payment_scope

router = APIRouter(prefix="/api/finance", tags=["finance"])

_PAYABLE = (APPROVED, SENT, PARTIALLY_RECEIVED, RECONCILIATION_REQUIRED, RECEIVED, PAYMENT_RECONCILIATION)
_VISIBLE = (*_PAYABLE, CLOSED)


def _build_outs(db: Session, purchase_orders: list[PurchaseOrder]) -> list[FinancePurchaseOrderOut]:
    if not purchase_orders:
        return []
    po_ids = [po.id for po in purchase_orders]
    lines = db.query(PurchaseOrderLine).filter(PurchaseOrderLine.purchase_order_id.in_(po_ids)).order_by(PurchaseOrderLine.id).all()
    payments = (
        db.query(PurchaseOrderPayment)
        .filter(PurchaseOrderPayment.purchase_order_id.in_(po_ids))
        .order_by(PurchaseOrderPayment.payment_date, PurchaseOrderPayment.id)
        .all()
    )
    materials = dict(db.query(RawMaterial.id, RawMaterial.name).filter(RawMaterial.id.in_({l.raw_material_id for l in lines})).all())
    units = dict(
        db.query(UnitOfMeasure.id, UnitOfMeasure.code).filter(UnitOfMeasure.id.in_({l.unit_of_measure_id for l in lines})).all()
    )
    suppliers = dict(db.query(Supplier.id, Supplier.name).filter(Supplier.id.in_({po.supplier_id for po in purchase_orders})).all())
    rfq_ids = {po.rfq_id for po in purchase_orders} - {None}
    rfqs = dict(db.query(Rfq.id, Rfq.rfq_number).filter(Rfq.id.in_(rfq_ids)).all()) if rfq_ids else {}

    out = []
    for po in purchase_orders:
        po_lines = [line for line in lines if line.purchase_order_id == po.id]
        po_payments = [p for p in payments if p.purchase_order_id == po.id]
        final = purchase_order_service.final_amount(po, po_lines)
        paid = purchase_order_service.paid_amount(po_payments)
        out.append(
            FinancePurchaseOrderOut(
                id=po.id,
                po_number=po.po_number,
                supplier_name=suppliers.get(po.supplier_id, ""),
                order_date=po.order_date,
                expected_delivery_date=po.expected_delivery_date,
                payment_terms=po.payment_terms,
                supplier_reference=po.supplier_reference,
                rfq_number=rfqs.get(po.rfq_id),
                notes=po.notes,
                status=po.status,
                approved_at=po.approved_at,
                currency=po.currency,
                final_amount=final,
                paid_amount=paid,
                outstanding_amount=max(final - paid, Decimal("0")),
                payment_status=purchase_order_service.payment_status(final, paid),
                lines=[
                    FinanceLineOut(
                        material_name=materials.get(line.raw_material_id, f"#{line.raw_material_id}"),
                        quantity=line.quantity - line.cancelled_quantity,
                        unit_code=units.get(line.unit_of_measure_id, ""),
                        unit_price=line.unit_price,
                        line_total=purchase_order_service.compute_line_total(line.quantity - line.cancelled_quantity, line.unit_price),
                    )
                    for line in po_lines
                ],
                payments=[
                    FinancePaymentOut(
                        id=p.id,
                        payment_number=p.payment_number,
                        payment_date=p.payment_date,
                        amount=p.amount,
                        payment_method=p.payment_method,
                        notes=p.notes,
                        status=p.status,
                    )
                    for p in po_payments
                ],
            )
        )
    return out


@router.get("/purchase-orders", response_model=PaginatedResponse[FinancePurchaseOrderOut])
def list_purchase_orders_for_payment(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    q: str | None = Query(None, max_length=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PaginatedResponse[FinancePurchaseOrderOut]:
    """Approved POs with an amount still to pay, oldest approval first.
    The outstanding amount is derived from lines and payments, so it is
    filtered here rather than in SQL (one organisation's open POs)."""
    purchase_payment_scope.require_permission(db, current_user, purchase_payment_scope.CREATE)
    query = db.query(PurchaseOrder).filter(
        PurchaseOrder.organisation_id == current_user.organisation_id, PurchaseOrder.status.in_(_PAYABLE)
    )
    query = apply_keyword_filter(query, q, PurchaseOrder.po_number)
    purchase_orders = query.order_by(PurchaseOrder.approved_at, PurchaseOrder.id).all()
    due = [po for po in _build_outs(db, purchase_orders) if po.outstanding_amount > 0]
    total = len(due)
    start = (page - 1) * page_size
    return PaginatedResponse(
        data=due[start : start + page_size],
        pagination=PaginationMeta(page=page, page_size=page_size, total=total, total_pages=ceil(total / page_size) if total else 0),
    )


@router.get("/purchase-orders/{purchase_order_id}", response_model=FinancePurchaseOrderOut)
def get_purchase_order_for_payment(
    purchase_order_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> FinancePurchaseOrderOut:
    purchase_payment_scope.require_permission(db, current_user, purchase_payment_scope.CREATE)
    purchase_order = (
        db.query(PurchaseOrder)
        .filter(
            PurchaseOrder.id == purchase_order_id,
            PurchaseOrder.organisation_id == current_user.organisation_id,
            PurchaseOrder.status.in_(_VISIBLE),
        )
        .first()
    )
    if purchase_order is None:
        raise NotFoundError("Purchase order not found.")
    return _build_outs(db, [purchase_order])[0]
