"""Warehouse goods receiving (docs/modules/purchase_orders.md Revision 6).

The warehouse records what physically arrived against a sent PO. Every
response here is `ReceivingOut` -- quantities, units, supplier, expected
date and receipt history only; never unit prices, line values, totals,
payments or commercial terms. Gated by `purchase:receive` alone, so a
warehouse user needs no `purchase:view` (which would expose prices).
The warehouse can't change the PO -- only add a receipt, which posts
stock immediately and is then reconciled automatically."""

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.purchase_orders import days_late, store_receipt_pdf
from app.core.database import get_db
from app.core.errors import NotFoundError, ValidationError
from app.core.list_query import paginate
from app.core.search import apply_keyword_filter
from app.models.audit_event import PROCUREMENT_MODULE, PURCHASE_ORDER_RECEIPT_POSTED
from app.models.file import FileRecord
from app.models.purchase_order import (
    CLOSED,
    PARTIALLY_RECEIVED,
    PAYMENT_RECONCILIATION,
    RECEIVED,
    RECONCILIATION_REQUIRED,
    SENT,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderReceipt,
    PurchaseOrderReceiptLine,
)
from app.models.raw_material import RawMaterial
from app.models.supplier import Supplier
from app.models.unit import UnitOfMeasure
from app.models.user import User
from app.models.warehouse import Warehouse
from app.schemas.file import FileOut
from app.schemas.pagination import PaginatedResponse
from app.schemas.purchase_order import (
    CreateReceiptRequest,
    ReceivingLineOut,
    ReceivingOut,
    ReceivingReceiptLineOut,
    ReceivingReceiptOut,
)
from app.services import audit_service, file_service, purchase_order_service, purchase_scope

router = APIRouter(prefix="/api/goods-receiving", tags=["goods-receiving"])

_RECEIVABLE = (SENT, PARTIALLY_RECEIVED)
_VISIBLE = (SENT, PARTIALLY_RECEIVED, RECONCILIATION_REQUIRED, RECEIVED, PAYMENT_RECONCILIATION, CLOSED)


def _get_po(db: Session, purchase_order_id: int, organisation_id: int) -> PurchaseOrder:
    purchase_order = (
        db.query(PurchaseOrder)
        .filter(
            PurchaseOrder.id == purchase_order_id,
            PurchaseOrder.organisation_id == organisation_id,
            PurchaseOrder.status.in_(_VISIBLE),
        )
        .first()
    )
    if purchase_order is None:
        raise NotFoundError("Purchase order not found.")
    return purchase_order


def _build_outs(db: Session, purchase_orders: list[PurchaseOrder]) -> list[ReceivingOut]:
    if not purchase_orders:
        return []
    po_ids = [po.id for po in purchase_orders]
    lines = db.query(PurchaseOrderLine).filter(PurchaseOrderLine.purchase_order_id.in_(po_ids)).order_by(PurchaseOrderLine.id).all()
    receipts = (
        db.query(PurchaseOrderReceipt)
        .filter(PurchaseOrderReceipt.purchase_order_id.in_(po_ids))
        .order_by(PurchaseOrderReceipt.id)
        .all()
    )
    receipt_lines = (
        db.query(PurchaseOrderReceiptLine)
        .filter(PurchaseOrderReceiptLine.receipt_id.in_([r.id for r in receipts]))
        .order_by(PurchaseOrderReceiptLine.id)
        .all()
        if receipts
        else []
    )
    documents: dict[int, list[FileRecord]] = {}
    if receipts:
        for record in (
            db.query(FileRecord)
            .filter(
                FileRecord.entity_type == "purchase_order_receipt",
                FileRecord.entity_id.in_([r.id for r in receipts]),
                FileRecord.deleted_at.is_(None),
            )
            .order_by(FileRecord.id)
        ):
            documents.setdefault(record.entity_id, []).append(record)

    materials = dict(db.query(RawMaterial.id, RawMaterial.name).filter(RawMaterial.id.in_({l.raw_material_id for l in lines})).all())
    units = dict(
        db.query(UnitOfMeasure.id, UnitOfMeasure.code).filter(UnitOfMeasure.id.in_({l.unit_of_measure_id for l in lines})).all()
    )
    suppliers = dict(db.query(Supplier.id, Supplier.name).filter(Supplier.id.in_({po.supplier_id for po in purchase_orders})).all())
    warehouses = dict(db.query(Warehouse.id, Warehouse.name).filter(Warehouse.id.in_({po.warehouse_id for po in purchase_orders})).all())
    user_ids = {r.posted_by_user_id or r.created_by_user_id for r in receipts} - {None}
    users = dict(db.query(User.id, User.full_name).filter(User.id.in_(user_ids)).all()) if user_ids else {}

    lines_by_id = {line.id: line for line in lines}
    out = []
    for po in purchase_orders:
        po_lines = [line for line in lines if line.purchase_order_id == po.id]
        po_receipts = [r for r in receipts if r.purchase_order_id == po.id]
        out.append(
            ReceivingOut(
                id=po.id,
                po_number=po.po_number,
                supplier_name=suppliers.get(po.supplier_id, ""),
                warehouse_name=warehouses.get(po.warehouse_id, ""),
                expected_delivery_date=po.expected_delivery_date,
                delivery_instructions=po.delivery_instructions,
                status=po.status,
                can_receive=po.status in _RECEIVABLE,
                lines=[
                    ReceivingLineOut(
                        id=line.id,
                        raw_material_id=line.raw_material_id,
                        material_name=materials.get(line.raw_material_id, f"#{line.raw_material_id}"),
                        unit_code=units.get(line.unit_of_measure_id, ""),
                        ordered_quantity=line.quantity - line.cancelled_quantity,
                        received_quantity=line.received_quantity,
                        remaining_quantity=max(line.quantity - line.cancelled_quantity - line.received_quantity, Decimal("0")),
                    )
                    for line in po_lines
                ],
                receipts=[
                    ReceivingReceiptOut(
                        id=receipt.id,
                        receipt_number=receipt.receipt_number,
                        receipt_date=receipt.receipt_date,
                        status=receipt.status,
                        posted_at=receipt.posted_at,
                        received_by_name=users.get(receipt.posted_by_user_id or receipt.created_by_user_id),
                        supplier_delivery_reference=receipt.supplier_delivery_reference,
                        notes=receipt.notes,
                        days_late=days_late(receipt.receipt_date, po.expected_delivery_date),
                        lines=[
                            ReceivingReceiptLineOut(
                                material_name=materials.get(rl.raw_material_id, f"#{rl.raw_material_id}"),
                                unit_code=units.get(lines_by_id[rl.purchase_order_line_id].unit_of_measure_id, "")
                                if rl.purchase_order_line_id in lines_by_id
                                else "",
                                quantity=rl.quantity,
                                remarks=rl.remarks,
                            )
                            for rl in receipt_lines
                            if rl.receipt_id == receipt.id
                        ],
                        documents=[FileOut.model_validate(f) for f in documents.get(receipt.id, [])],
                    )
                    for receipt in po_receipts
                ],
            )
        )
    return out


@router.get("", response_model=PaginatedResponse[ReceivingOut])
def list_receivable(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    q: str | None = Query(None, max_length=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PaginatedResponse[ReceivingOut]:
    """POs sent to suppliers and still awaiting goods, soonest expected
    first."""
    purchase_scope.require_permission(db, current_user, purchase_scope.RECEIVE)
    query = db.query(PurchaseOrder).filter(
        PurchaseOrder.organisation_id == current_user.organisation_id, PurchaseOrder.status.in_(_RECEIVABLE)
    )
    query = apply_keyword_filter(query, q, PurchaseOrder.po_number)
    query = query.order_by(PurchaseOrder.expected_delivery_date, PurchaseOrder.id)
    purchase_orders, pagination = paginate(query, page, page_size)
    return PaginatedResponse(data=_build_outs(db, purchase_orders), pagination=pagination)


@router.get("/{purchase_order_id}", response_model=ReceivingOut)
def get_receivable(
    purchase_order_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> ReceivingOut:
    purchase_scope.require_permission(db, current_user, purchase_scope.RECEIVE)
    return _build_outs(db, [_get_po(db, purchase_order_id, current_user.organisation_id)])[0]


@router.post("/{purchase_order_id}/receipts", response_model=ReceivingOut, status_code=status.HTTP_201_CREATED)
def submit_receipt(
    purchase_order_id: int,
    payload: CreateReceiptRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReceivingOut:
    """Submit Receipt: records what arrived, posts it to stock, then
    reconciles automatically -- a short line returns the PO to its
    creator; a late delivery is shown, not blocking. One commit."""
    purchase_scope.require_permission(db, current_user, purchase_scope.RECEIVE)
    purchase_order = _get_po(db, purchase_order_id, current_user.organisation_id)
    if payload.receipt_date > date.today():
        raise ValidationError("Receipt date cannot be in the future.", fields={"receipt_date": "Cannot be in the future."})

    receipt = purchase_order_service.create_receipt(
        db,
        purchase_order=purchase_order,
        receipt_date=payload.receipt_date,
        supplier_delivery_reference=payload.supplier_delivery_reference,
        notes=payload.notes,
        entries=[(line.purchase_order_line_id, line.quantity) for line in payload.lines],
        created_by_user_id=current_user.id,
        remarks={line.purchase_order_line_id: line.remarks for line in payload.lines},
    )
    if payload.file_ids:
        file_service.attach_files(
            db,
            file_ids=payload.file_ids,
            entity_type="purchase_order_receipt",
            entity_id=receipt.id,
            organisation_id=current_user.organisation_id,
        )
    purchase_order_service.post_receipt(db, receipt=receipt, purchase_order=purchase_order, posted_by_user_id=current_user.id)
    audit_service.log_event(
        db,
        action=PURCHASE_ORDER_RECEIPT_POSTED,
        module=PROCUREMENT_MODULE,
        organisation_id=current_user.organisation_id,
        actor_user_id=current_user.id,
        entity_type="purchase_order",
        entity_id=purchase_order.id,
        result="success",
        details=f"receipt_number: {receipt.receipt_number}, po status: {purchase_order.status}",
        ip_address=request.client.host if request.client else None,
    )
    store_receipt_pdf(db, purchase_order, receipt, current_user)
    db.refresh(purchase_order)
    return _build_outs(db, [purchase_order])[0]
