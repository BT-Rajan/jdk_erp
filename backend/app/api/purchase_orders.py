import io
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.entity_access import register_entity_access_check
from app.core.errors import BusinessRuleError, NotFoundError, ValidationError
from app.core.list_query import apply_sort, paginate
from app.core.search import apply_keyword_filter
from app.core.storage import default_storage
from app.models.audit_event import (
    PROCUREMENT_MODULE,
    PURCHASE_ORDER_CREATED,
    PURCHASE_ORDER_ISSUED,
    PURCHASE_ORDER_LINE_ADDED,
    PURCHASE_ORDER_LINE_REMOVED,
    PURCHASE_ORDER_LINE_UPDATED,
    PURCHASE_ORDER_PAYMENT_CANCELLED,
    PURCHASE_ORDER_PAYMENT_RECORDED,
    PURCHASE_ORDER_RECEIPT_CANCELLED,
    PURCHASE_ORDER_RECEIPT_CREATED,
    PURCHASE_ORDER_RECEIPT_POSTED,
    PURCHASE_ORDER_RECEIPT_REVERSED,
    PURCHASE_ORDER_SEND_FAILED,
    PURCHASE_ORDER_SENT,
    PURCHASE_ORDER_STATUS_CHANGED,
    PURCHASE_ORDER_SUPPLIER_CONFIRMED,
    PURCHASE_ORDER_UPDATED,
)
from app.models.file import FileRecord
from app.models.organisation import Organisation
from app.models.purchase_order import (
    CANCELLED,
    DRAFT,
    ISSUED,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderPayment,
    PurchaseOrderReceipt,
    PurchaseOrderReceiptLine,
    PurchaseOrderRevision,
    PurchaseOrderRevisionLine,
)
from app.models.raw_material import RawMaterial
from app.models.supplier import Supplier
from app.models.unit import UnitOfMeasure
from app.models.user import User
from app.models.warehouse import Warehouse
from app.schemas.file import FileOut
from app.schemas.purchase_order import (
    CancelPaymentRequest,
    ConfirmSupplierRequest,
    CreateReceiptRequest,
    PurchaseOrderCreateRequest,
    PurchaseOrderLineCreateRequest,
    PurchaseOrderLineOut,
    PurchaseOrderLineUpdateRequest,
    PurchaseOrderOut,
    PurchaseOrderPaymentOut,
    PurchaseOrderReceiptLineOut,
    PurchaseOrderReceiptOut,
    PurchaseOrderRevisionLineOut,
    PurchaseOrderRevisionOut,
    PurchaseOrderStatusChangeRequest,
    PurchaseOrderUpdateRequest,
    RecordPaymentRequest,
    ReverseReceiptRequest,
)
from app.schemas.pagination import PaginatedResponse
from app.services import audit_service, email_service, file_service, purchase_order_service, purchase_payment_scope, purchase_scope
from app.services.purchase_order_pdf_service import PurchaseOrderPdfData, PurchaseOrderPdfLine, generate_purchase_order_pdf
from app.services.purchase_order_receipt_pdf_service import (
    PurchaseOrderReceiptPdfData,
    PurchaseOrderReceiptPdfLine,
    generate_purchase_order_receipt_pdf,
)

router = APIRouter(prefix="/api/purchase-orders", tags=["purchase-orders"])

_SORT_FIELDS = {
    "po_number": PurchaseOrder.po_number,
    "order_date": PurchaseOrder.order_date,
    "status": PurchaseOrder.status,
    "created_at": PurchaseOrder.created_at,
}

_PURCHASE_ORDER_ENTITY = "purchase_order"
_PURCHASE_ORDER_REVISION_ENTITY = "purchase_order_revision"
_PURCHASE_ORDER_PAYMENT_ENTITY = "purchase_order_payment"
_PURCHASE_ORDER_RECEIPT_ENTITY = "purchase_order_receipt"


def _get_po_in_org(db: Session, purchase_order_id: int, organisation_id: int) -> PurchaseOrder:
    purchase_order = (
        db.query(PurchaseOrder)
        .filter(PurchaseOrder.id == purchase_order_id, PurchaseOrder.organisation_id == organisation_id)
        .first()
    )
    if purchase_order is None:
        # 404 whether the id doesn't exist at all or belongs to another
        # organisation -- never confirm another organisation's purchase
        # order id (docs/modules/organisation.md #3).
        raise NotFoundError("Purchase order not found.")
    return purchase_order


def _get_payment_in_po(db: Session, purchase_order_id: int, payment_id: int) -> PurchaseOrderPayment:
    payment = (
        db.query(PurchaseOrderPayment)
        .filter(PurchaseOrderPayment.id == payment_id, PurchaseOrderPayment.purchase_order_id == purchase_order_id)
        .first()
    )
    if payment is None:
        raise NotFoundError("Payment not found.")
    return payment


def _get_receipt_in_po(db: Session, purchase_order_id: int, receipt_id: int) -> PurchaseOrderReceipt:
    receipt = (
        db.query(PurchaseOrderReceipt)
        .filter(PurchaseOrderReceipt.id == receipt_id, PurchaseOrderReceipt.purchase_order_id == purchase_order_id)
        .first()
    )
    if receipt is None:
        raise NotFoundError("Goods receipt not found.")
    return receipt


def _get_line_in_po(db: Session, purchase_order_id: int, line_id: int) -> PurchaseOrderLine:
    line = (
        db.query(PurchaseOrderLine)
        .filter(PurchaseOrderLine.id == line_id, PurchaseOrderLine.purchase_order_id == purchase_order_id)
        .first()
    )
    if line is None:
        raise NotFoundError("Purchase order line not found.")
    return line


def _resolve_active_supplier(db: Session, supplier_id: int, organisation_id: int) -> Supplier:
    supplier = (
        db.query(Supplier)
        .filter(Supplier.id == supplier_id, Supplier.organisation_id == organisation_id, Supplier.is_active.is_(True))
        .first()
    )
    if supplier is None:
        raise ValidationError(
            "supplier_id must be an active supplier in your organisation.",
            fields={"supplier_id": "Not a valid active supplier in your organisation."},
        )
    return supplier


def _resolve_active_warehouse(db: Session, warehouse_id: int, organisation_id: int) -> Warehouse:
    warehouse = (
        db.query(Warehouse)
        .filter(Warehouse.id == warehouse_id, Warehouse.organisation_id == organisation_id, Warehouse.is_active.is_(True))
        .first()
    )
    if warehouse is None:
        raise ValidationError(
            "warehouse_id must be an active warehouse in your organisation.",
            fields={"warehouse_id": "Not a valid active warehouse in your organisation."},
        )
    return warehouse


def _resolve_active_raw_material(db: Session, raw_material_id: int, organisation_id: int) -> RawMaterial:
    material = (
        db.query(RawMaterial)
        .filter(
            RawMaterial.id == raw_material_id,
            RawMaterial.organisation_id == organisation_id,
            RawMaterial.is_active.is_(True),
        )
        .first()
    )
    if material is None:
        raise ValidationError(
            "raw_material_id must be an active raw material in your organisation.",
            fields={"raw_material_id": "Not a valid active raw material in your organisation."},
        )
    return material


def _require_draft(purchase_order: PurchaseOrder) -> None:
    if purchase_order.status != DRAFT:
        raise BusinessRuleError("Only a draft purchase order can be edited.")


def _build_revision_out(db: Session, revision: PurchaseOrderRevision) -> PurchaseOrderRevisionOut:
    lines = (
        db.query(PurchaseOrderRevisionLine)
        .filter(PurchaseOrderRevisionLine.revision_id == revision.id)
        .order_by(PurchaseOrderRevisionLine.id)
        .all()
    )
    pdf_file = (
        db.query(FileRecord)
        .filter(
            FileRecord.entity_type == _PURCHASE_ORDER_REVISION_ENTITY,
            FileRecord.entity_id == revision.id,
            FileRecord.deleted_at.is_(None),
        )
        .first()
    )
    return PurchaseOrderRevisionOut(
        id=revision.id,
        revision_number=revision.revision_number,
        order_date=revision.order_date,
        expected_delivery_date=revision.expected_delivery_date,
        supplier_reference=revision.supplier_reference,
        payment_terms=revision.payment_terms,
        notes=revision.notes,
        total_amount=revision.total_amount,
        issued_at=revision.issued_at,
        issued_by_user_id=revision.issued_by_user_id,
        lines=[PurchaseOrderRevisionLineOut.model_validate(line) for line in lines],
        pdf_file=FileOut.model_validate(pdf_file) if pdf_file else None,
    )


def _build_payment_out(db: Session, payment: PurchaseOrderPayment) -> PurchaseOrderPaymentOut:
    files = (
        db.query(FileRecord)
        .filter(
            FileRecord.entity_type == _PURCHASE_ORDER_PAYMENT_ENTITY,
            FileRecord.entity_id == payment.id,
            FileRecord.deleted_at.is_(None),
        )
        .order_by(FileRecord.id)
        .all()
    )
    out = PurchaseOrderPaymentOut.model_validate(payment)
    out.files = [FileOut.model_validate(f) for f in files]
    return out


def _build_receipt_out(db: Session, receipt: PurchaseOrderReceipt) -> PurchaseOrderReceiptOut:
    lines = (
        db.query(PurchaseOrderReceiptLine)
        .filter(PurchaseOrderReceiptLine.receipt_id == receipt.id)
        .order_by(PurchaseOrderReceiptLine.id)
        .all()
    )
    files = (
        db.query(FileRecord)
        .filter(
            FileRecord.entity_type == _PURCHASE_ORDER_RECEIPT_ENTITY,
            FileRecord.entity_id == receipt.id,
            FileRecord.deleted_at.is_(None),
        )
        .order_by(FileRecord.id)
        .all()
    )
    out = PurchaseOrderReceiptOut.model_validate(receipt)
    out.lines = [PurchaseOrderReceiptLineOut.model_validate(line) for line in lines]
    out.documents = [FileOut.model_validate(f) for f in files]
    return out


def _build_po_out(db: Session, purchase_order: PurchaseOrder) -> PurchaseOrderOut:
    lines = (
        db.query(PurchaseOrderLine)
        .filter(PurchaseOrderLine.purchase_order_id == purchase_order.id)
        .order_by(PurchaseOrderLine.id)
        .all()
    )
    payments = (
        db.query(PurchaseOrderPayment)
        .filter(PurchaseOrderPayment.purchase_order_id == purchase_order.id)
        .order_by(PurchaseOrderPayment.id)
        .all()
    )
    revisions = (
        db.query(PurchaseOrderRevision)
        .filter(PurchaseOrderRevision.purchase_order_id == purchase_order.id)
        .order_by(PurchaseOrderRevision.revision_number)
        .all()
    )
    receipts = (
        db.query(PurchaseOrderReceipt)
        .filter(PurchaseOrderReceipt.purchase_order_id == purchase_order.id)
        .order_by(PurchaseOrderReceipt.id)
        .all()
    )
    documents = (
        db.query(FileRecord)
        .filter(
            FileRecord.entity_type == _PURCHASE_ORDER_ENTITY,
            FileRecord.entity_id == purchase_order.id,
            FileRecord.deleted_at.is_(None),
        )
        .order_by(FileRecord.id)
        .all()
    )
    return PurchaseOrderOut(
        id=purchase_order.id,
        organisation_id=purchase_order.organisation_id,
        po_number=purchase_order.po_number,
        supplier_id=purchase_order.supplier_id,
        warehouse_id=purchase_order.warehouse_id,
        rfq_id=purchase_order.rfq_id,
        status=purchase_order.status,
        revision_number=purchase_order.revision_number,
        order_date=purchase_order.order_date,
        expected_delivery_date=purchase_order.expected_delivery_date,
        supplier_reference=purchase_order.supplier_reference,
        payment_terms=purchase_order.payment_terms,
        notes=purchase_order.notes,
        cancel_reason=purchase_order.cancel_reason,
        supplier_confirmed_at=purchase_order.supplier_confirmed_at,
        supplier_confirmed_by_user_id=purchase_order.supplier_confirmed_by_user_id,
        supplier_confirmation_note=purchase_order.supplier_confirmation_note,
        total_amount=purchase_order_service.total_amount(lines),
        paid_amount=purchase_order_service.paid_amount(payments),
        outstanding_amount=purchase_order_service.total_amount(lines) - purchase_order_service.paid_amount(payments),
        lines=[PurchaseOrderLineOut.model_validate(line) for line in lines],
        revisions=[_build_revision_out(db, revision) for revision in revisions],
        documents=[FileOut.model_validate(f) for f in documents],
        payments=[_build_payment_out(db, payment) for payment in payments],
        receipts=[_build_receipt_out(db, receipt) for receipt in receipts],
    )


@router.get("", response_model=PaginatedResponse[PurchaseOrderOut])
def list_purchase_orders(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    sort_by: str | None = Query(None),
    sort_direction: Literal["asc", "desc"] = Query("asc"),
    status_filter: str | None = Query(None, alias="status"),
    supplier_id: int | None = Query(None),
    q: str | None = Query(None, max_length=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PaginatedResponse[PurchaseOrderOut]:
    """Scoped to the caller's own organisation, gated by the "view"
    purchase permission (docs/modules/purchase_orders.md #13) -- no
    OWN/TEAM narrowing, every grant sees every PO in the organisation."""
    purchase_scope.require_permission(db, current_user, purchase_scope.VIEW)

    query = db.query(PurchaseOrder).filter(PurchaseOrder.organisation_id == current_user.organisation_id)
    if status_filter is not None:
        query = query.filter(PurchaseOrder.status == status_filter)
    if supplier_id is not None:
        query = query.filter(PurchaseOrder.supplier_id == supplier_id)
    query = apply_keyword_filter(query, q, PurchaseOrder.po_number)
    query = apply_sort(query, sort_by, sort_direction, _SORT_FIELDS, default=PurchaseOrder.id)

    purchase_orders, pagination = paginate(query, page, page_size)
    return PaginatedResponse(data=[_build_po_out(db, po) for po in purchase_orders], pagination=pagination)


@router.get("/{purchase_order_id}", response_model=PurchaseOrderOut)
def get_purchase_order(
    purchase_order_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> PurchaseOrderOut:
    purchase_scope.require_permission(db, current_user, purchase_scope.VIEW)
    purchase_order = _get_po_in_org(db, purchase_order_id, current_user.organisation_id)
    return _build_po_out(db, purchase_order)


@router.post("", response_model=PurchaseOrderOut, status_code=status.HTTP_201_CREATED)
def create_purchase_order(
    payload: PurchaseOrderCreateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PurchaseOrderOut:
    """Always starts `draft` and empty -- lines are added afterward via
    POST .../lines (docs/modules/purchase_orders.md #2/#3). `rfq_id` is
    never set here -- only app/api/rfqs.py's convert-to-PO action sets it
    (docs/modules/purchase_orders.md #22)."""
    purchase_scope.require_permission(db, current_user, purchase_scope.CREATE)
    _resolve_active_supplier(db, payload.supplier_id, current_user.organisation_id)
    _resolve_active_warehouse(db, payload.warehouse_id, current_user.organisation_id)

    purchase_order = purchase_order_service.create_purchase_order_with_lines(
        db,
        organisation_id=current_user.organisation_id,
        supplier_id=payload.supplier_id,
        warehouse_id=payload.warehouse_id,
        order_date=payload.order_date,
        expected_delivery_date=payload.expected_delivery_date,
        notes=payload.notes,
        lines=[],
    )
    purchase_order.supplier_reference = payload.supplier_reference
    purchase_order.payment_terms = payload.payment_terms
    db.add(purchase_order)
    db.flush()

    audit_service.log_event(
        db,
        action=PURCHASE_ORDER_CREATED,
        module=PROCUREMENT_MODULE,
        organisation_id=current_user.organisation_id,
        actor_user_id=current_user.id,
        entity_type=_PURCHASE_ORDER_ENTITY,
        entity_id=purchase_order.id,
        result="success",
        details=f"po_number: {purchase_order.po_number}, supplier_id: {purchase_order.supplier_id}",
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    db.refresh(purchase_order)
    return _build_po_out(db, purchase_order)


@router.patch("/{purchase_order_id}", response_model=PurchaseOrderOut)
def update_purchase_order(
    purchase_order_id: int,
    payload: PurchaseOrderUpdateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PurchaseOrderOut:
    """Draft-only (docs/modules/purchase_orders.md #6) --
    supplier_id/warehouse_id/rfq_id are immutable and have no update path
    here."""
    purchase_scope.require_permission(db, current_user, purchase_scope.CREATE)
    purchase_order = _get_po_in_org(db, purchase_order_id, current_user.organisation_id)
    _require_draft(purchase_order)

    updates = payload.model_dump(exclude_unset=True)
    before = {field: getattr(purchase_order, field) for field in updates}
    for field, value in updates.items():
        setattr(purchase_order, field, value)
    db.add(purchase_order)
    db.flush()

    changes = audit_service.diff_fields(before, updates)
    if changes:
        audit_service.log_event(
            db,
            action=PURCHASE_ORDER_UPDATED,
            module=PROCUREMENT_MODULE,
            organisation_id=current_user.organisation_id,
            actor_user_id=current_user.id,
            entity_type=_PURCHASE_ORDER_ENTITY,
            entity_id=purchase_order.id,
            result="success",
            details=audit_service.format_changes(changes),
            ip_address=request.client.host if request.client else None,
        )
    db.commit()
    db.refresh(purchase_order)
    return _build_po_out(db, purchase_order)


@router.post("/{purchase_order_id}/lines", response_model=PurchaseOrderOut, status_code=status.HTTP_201_CREATED)
def add_purchase_order_line(
    purchase_order_id: int,
    payload: PurchaseOrderLineCreateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PurchaseOrderOut:
    """Draft-only. `unit_price` defaults from RawMaterial.reference_cost
    when omitted (docs/modules/purchase_orders.md #3);
    `line_total`/`unit_price` are snapshotted onto the line, never read
    live afterward."""
    purchase_scope.require_permission(db, current_user, purchase_scope.CREATE)
    purchase_order = _get_po_in_org(db, purchase_order_id, current_user.organisation_id)
    _require_draft(purchase_order)
    material = _resolve_active_raw_material(db, payload.raw_material_id, current_user.organisation_id)

    unit_price = purchase_order_service.resolve_unit_price(material, payload.unit_price)
    line_total = purchase_order_service.compute_line_total(payload.quantity, unit_price)

    line = PurchaseOrderLine(
        purchase_order_id=purchase_order.id,
        raw_material_id=payload.raw_material_id,
        quantity=payload.quantity,
        unit_price=unit_price,
        line_total=line_total,
    )
    db.add(line)
    db.flush()

    audit_service.log_event(
        db,
        action=PURCHASE_ORDER_LINE_ADDED,
        module=PROCUREMENT_MODULE,
        organisation_id=current_user.organisation_id,
        actor_user_id=current_user.id,
        entity_type=_PURCHASE_ORDER_ENTITY,
        entity_id=purchase_order.id,
        result="success",
        details=f"raw_material_id: {line.raw_material_id}, quantity: {line.quantity}, unit_price: {line.unit_price}",
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    db.refresh(purchase_order)
    return _build_po_out(db, purchase_order)


@router.patch("/{purchase_order_id}/lines/{line_id}", response_model=PurchaseOrderOut)
def update_purchase_order_line(
    purchase_order_id: int,
    line_id: int,
    payload: PurchaseOrderLineUpdateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PurchaseOrderOut:
    """Draft-only. `raw_material_id` is immutable; changing `quantity`/
    `unit_price` always recomputes `line_total`."""
    purchase_scope.require_permission(db, current_user, purchase_scope.CREATE)
    purchase_order = _get_po_in_org(db, purchase_order_id, current_user.organisation_id)
    _require_draft(purchase_order)
    line = _get_line_in_po(db, purchase_order.id, line_id)

    updates = payload.model_dump(exclude_unset=True)
    quantity = updates.get("quantity", line.quantity)
    unit_price = updates.get("unit_price", line.unit_price)
    line.quantity = quantity
    line.unit_price = unit_price
    line.line_total = purchase_order_service.compute_line_total(quantity, unit_price)
    db.add(line)
    db.flush()

    audit_service.log_event(
        db,
        action=PURCHASE_ORDER_LINE_UPDATED,
        module=PROCUREMENT_MODULE,
        organisation_id=current_user.organisation_id,
        actor_user_id=current_user.id,
        entity_type=_PURCHASE_ORDER_ENTITY,
        entity_id=purchase_order.id,
        result="success",
        details=f"line_id: {line.id}, quantity: {line.quantity}, unit_price: {line.unit_price}",
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    db.refresh(purchase_order)
    return _build_po_out(db, purchase_order)


@router.delete("/{purchase_order_id}/lines/{line_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_purchase_order_line(
    purchase_order_id: int,
    line_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """Draft-only. A real delete -- a draft line has no issued revision
    to protect yet (a line can only be part of a revision snapshot once
    the PO has been issued -- docs/modules/purchase_orders.md #24)."""
    purchase_scope.require_permission(db, current_user, purchase_scope.CREATE)
    purchase_order = _get_po_in_org(db, purchase_order_id, current_user.organisation_id)
    _require_draft(purchase_order)
    line = _get_line_in_po(db, purchase_order.id, line_id)

    audit_service.log_event(
        db,
        action=PURCHASE_ORDER_LINE_REMOVED,
        module=PROCUREMENT_MODULE,
        organisation_id=current_user.organisation_id,
        actor_user_id=current_user.id,
        entity_type=_PURCHASE_ORDER_ENTITY,
        entity_id=purchase_order.id,
        result="success",
        details=f"raw_material_id: {line.raw_material_id}",
        ip_address=request.client.host if request.client else None,
    )
    db.delete(line)
    db.commit()


@router.patch("/{purchase_order_id}/status", response_model=PurchaseOrderOut)
def change_purchase_order_status(
    purchase_order_id: int,
    payload: PurchaseOrderStatusChangeRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PurchaseOrderOut:
    """Reopen for a new revision (`draft`, "Create Revision") or cancel
    (docs/modules/purchase_orders.md #23) -- gated by the "issue"
    purchase permission, which covers every PO-lifecycle decision that
    isn't its own dedicated action (issue/confirm-supplier/receive)."""
    purchase_scope.require_permission(db, current_user, purchase_scope.ISSUE)
    purchase_order = _get_po_in_org(db, purchase_order_id, current_user.organisation_id)
    purchase_order_service.assert_transition_allowed(purchase_order.status, payload.status)

    before_status = purchase_order.status
    purchase_order.status = payload.status
    if payload.status == CANCELLED:
        purchase_order.cancel_reason = payload.cancel_reason
    db.add(purchase_order)

    audit_service.log_event(
        db,
        action=PURCHASE_ORDER_STATUS_CHANGED,
        module=PROCUREMENT_MODULE,
        organisation_id=current_user.organisation_id,
        actor_user_id=current_user.id,
        entity_type=_PURCHASE_ORDER_ENTITY,
        entity_id=purchase_order.id,
        result="success",
        details=f"status: {before_status} -> {payload.status}"
        + (f", reason: {payload.cancel_reason}" if payload.status == CANCELLED else ""),
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    db.refresh(purchase_order)
    return _build_po_out(db, purchase_order)


@router.post("/{purchase_order_id}/issue", response_model=PurchaseOrderOut)
def issue_purchase_order(
    purchase_order_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PurchaseOrderOut:
    """`draft -> issued` (docs/modules/purchase_orders.md #23/#24/#27):
    snapshots the current header/lines into a new immutable revision, then
    renders and stores that revision's official PDF -- never regenerated
    later even if the organisation's letterhead details change."""
    purchase_scope.require_permission(db, current_user, purchase_scope.ISSUE)
    purchase_order = _get_po_in_org(db, purchase_order_id, current_user.organisation_id)
    supplier = _resolve_active_supplier(db, purchase_order.supplier_id, current_user.organisation_id)

    revision = purchase_order_service.issue_purchase_order(db, purchase_order=purchase_order, issued_by_user_id=current_user.id)

    revision_lines = (
        db.query(PurchaseOrderRevisionLine).filter(PurchaseOrderRevisionLine.revision_id == revision.id).order_by(PurchaseOrderRevisionLine.id).all()
    )
    materials_by_id = {
        m.id: m
        for m in db.query(RawMaterial).filter(RawMaterial.id.in_([line.raw_material_id for line in revision_lines])).all()
    }
    organisation = db.query(Organisation).filter(Organisation.id == current_user.organisation_id).first()

    pdf_bytes = generate_purchase_order_pdf(
        PurchaseOrderPdfData(
            organisation_name=organisation.name,
            organisation_address=organisation.address,
            organisation_phone=organisation.contact_phone,
            organisation_email=organisation.contact_email,
            po_number=purchase_order.po_number,
            revision_number=revision.revision_number,
            order_date=revision.order_date,
            expected_delivery_date=revision.expected_delivery_date,
            supplier_reference=revision.supplier_reference,
            payment_terms=revision.payment_terms,
            notes=revision.notes,
            supplier_name=supplier.name,
            supplier_address=supplier.address,
            supplier_contact_person=supplier.contact_person,
            supplier_phone=supplier.phone,
            supplier_email=supplier.email,
            lines=[
                PurchaseOrderPdfLine(
                    material_name=materials_by_id[line.raw_material_id].name if line.raw_material_id in materials_by_id else f"#{line.raw_material_id}",
                    quantity=line.quantity,
                    unit_price=line.unit_price,
                    line_total=line.line_total,
                )
                for line in revision_lines
            ],
            total_amount=revision.total_amount,
            issued_at=revision.issued_at,
        )
    )
    # upload_file commits internally (app/services/file_service.py) --
    # this is the one commit point for the revision snapshot, its lines,
    # the status flip, and the PDF file record together (docs/modules/
    # purchase_orders.md #23's "Issue Revision" transaction boundary).
    file_service.upload_file(
        db,
        organisation_id=current_user.organisation_id,
        uploaded_by_user_id=current_user.id,
        filename=f"{purchase_order.po_number}-Rev{revision.revision_number}.pdf",
        stream=io.BytesIO(pdf_bytes),
        entity_type=_PURCHASE_ORDER_REVISION_ENTITY,
        entity_id=revision.id,
    )

    audit_service.log_event(
        db,
        action=PURCHASE_ORDER_ISSUED,
        module=PROCUREMENT_MODULE,
        organisation_id=current_user.organisation_id,
        actor_user_id=current_user.id,
        entity_type=_PURCHASE_ORDER_ENTITY,
        entity_id=purchase_order.id,
        result="success",
        details=f"revision: {revision.revision_number}, total_amount: {revision.total_amount}",
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    db.refresh(purchase_order)
    return _build_po_out(db, purchase_order)


@router.post("/{purchase_order_id}/confirm-supplier", response_model=PurchaseOrderOut)
def confirm_supplier(
    purchase_order_id: int,
    payload: ConfirmSupplierRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PurchaseOrderOut:
    """`issued -> supplier_confirmed` (docs/modules/purchase_orders.md
    #25) -- a distinct event from issuing/sending. Evidence attachment
    reuses the same file_service.attach_files flow RFQ response capture
    already established (docs/modules/rfq.md #5/#15)."""
    purchase_scope.require_permission(db, current_user, purchase_scope.CONFIRM_SUPPLIER)
    purchase_order = _get_po_in_org(db, purchase_order_id, current_user.organisation_id)

    purchase_order_service.confirm_supplier(
        db, purchase_order=purchase_order, note=payload.note, confirmed_by_user_id=current_user.id
    )
    if payload.file_ids:
        file_service.attach_files(
            db,
            file_ids=payload.file_ids,
            entity_type=_PURCHASE_ORDER_ENTITY,
            entity_id=purchase_order.id,
            organisation_id=current_user.organisation_id,
        )

    audit_service.log_event(
        db,
        action=PURCHASE_ORDER_SUPPLIER_CONFIRMED,
        module=PROCUREMENT_MODULE,
        organisation_id=current_user.organisation_id,
        actor_user_id=current_user.id,
        entity_type=_PURCHASE_ORDER_ENTITY,
        entity_id=purchase_order.id,
        result="success",
        details=f"note: {payload.note}, files: {len(payload.file_ids)}",
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    db.refresh(purchase_order)
    return _build_po_out(db, purchase_order)


@router.post("/{purchase_order_id}/send", response_model=PurchaseOrderOut)
def send_purchase_order(
    purchase_order_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PurchaseOrderOut:
    """Emails the current revision's already-generated, immutable PDF to
    the supplier via the existing native email integration
    (docs/modules/purchase_orders.md #27) -- never regenerates it. A
    failed send is recorded and re-raised before anything is marked
    successfully sent (the same immediate-commit-on-failure pattern
    app/services/auth_service.py's login lockout counter already
    established for a "must persist even though we're about to error"
    case)."""
    purchase_scope.require_permission(db, current_user, purchase_scope.SEND)
    purchase_order = _get_po_in_org(db, purchase_order_id, current_user.organisation_id)
    if purchase_order.status != ISSUED:
        raise BusinessRuleError("Only an issued purchase order can be sent.")

    revision = (
        db.query(PurchaseOrderRevision)
        .filter(
            PurchaseOrderRevision.purchase_order_id == purchase_order.id,
            PurchaseOrderRevision.revision_number == purchase_order.revision_number,
        )
        .first()
    )
    pdf_file = (
        db.query(FileRecord)
        .filter(
            FileRecord.entity_type == _PURCHASE_ORDER_REVISION_ENTITY,
            FileRecord.entity_id == revision.id,
            FileRecord.deleted_at.is_(None),
        )
        .first()
    )
    if pdf_file is None:
        raise BusinessRuleError("No document has been generated for this revision yet.")

    supplier = db.query(Supplier).filter(Supplier.id == purchase_order.supplier_id).first()
    if not supplier.email:
        raise ValidationError(
            "This supplier has no email address on file.", fields={"supplier_id": "Missing email address."}
        )

    pdf_bytes = b"".join(default_storage.download(pdf_file.storage_key))
    subject = f"Purchase Order {purchase_order.po_number} (Revision {revision.revision_number})"
    body = (
        f"Dear {supplier.name},\n\nPlease find attached Purchase Order {purchase_order.po_number} "
        f"(Revision {revision.revision_number}).\n\nRegards."
    )

    try:
        email_service.send_email(
            db, current_user.organisation_id, supplier.email, subject, body, pdf_bytes, pdf_file.original_filename
        )
    except BusinessRuleError as exc:
        audit_service.log_event(
            db,
            action=PURCHASE_ORDER_SEND_FAILED,
            module=PROCUREMENT_MODULE,
            organisation_id=current_user.organisation_id,
            actor_user_id=current_user.id,
            entity_type=_PURCHASE_ORDER_ENTITY,
            entity_id=purchase_order.id,
            result="failure",
            details=str(exc),
            ip_address=request.client.host if request.client else None,
        )
        db.commit()
        raise

    audit_service.log_event(
        db,
        action=PURCHASE_ORDER_SENT,
        module=PROCUREMENT_MODULE,
        organisation_id=current_user.organisation_id,
        actor_user_id=current_user.id,
        entity_type=_PURCHASE_ORDER_ENTITY,
        entity_id=purchase_order.id,
        result="success",
        details=f"revision: {revision.revision_number}, to: {supplier.email}",
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    db.refresh(purchase_order)
    return _build_po_out(db, purchase_order)


@router.post("/{purchase_order_id}/receipts", response_model=PurchaseOrderOut, status_code=status.HTTP_201_CREATED)
def create_receipt(
    purchase_order_id: int,
    payload: CreateReceiptRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PurchaseOrderOut:
    """docs/modules/purchase_orders.md #37/#39, Revision 4 -- starts a
    `draft` Goods Receipt against this PO's lines; zero inventory effect
    until it's posted (#38). Reuses the `purchase_scope.RECEIVE`
    permission that already gated the removed single-call receive
    action -- receiving is still one lifecycle step of the PO, not a
    separately permissioned module."""
    purchase_scope.require_permission(db, current_user, purchase_scope.RECEIVE)
    purchase_order = _get_po_in_org(db, purchase_order_id, current_user.organisation_id)

    entries = [(line.purchase_order_line_id, line.quantity) for line in payload.lines]
    receipt = purchase_order_service.create_receipt(
        db,
        purchase_order=purchase_order,
        receipt_date=payload.receipt_date,
        supplier_delivery_reference=payload.supplier_delivery_reference,
        notes=payload.notes,
        entries=entries,
        created_by_user_id=current_user.id,
    )
    if payload.file_ids:
        file_service.attach_files(
            db,
            file_ids=payload.file_ids,
            entity_type=_PURCHASE_ORDER_RECEIPT_ENTITY,
            entity_id=receipt.id,
            organisation_id=current_user.organisation_id,
        )

    audit_service.log_event(
        db,
        action=PURCHASE_ORDER_RECEIPT_CREATED,
        module=PROCUREMENT_MODULE,
        organisation_id=current_user.organisation_id,
        actor_user_id=current_user.id,
        entity_type=_PURCHASE_ORDER_ENTITY,
        entity_id=purchase_order.id,
        result="success",
        details=f"receipt_number: {receipt.receipt_number}, lines: {len(entries)}",
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    db.refresh(purchase_order)
    return _build_po_out(db, purchase_order)


@router.post("/{purchase_order_id}/receipts/{receipt_id}/post", response_model=PurchaseOrderOut)
def post_receipt(
    purchase_order_id: int,
    receipt_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PurchaseOrderOut:
    """`draft -> posted` (docs/modules/purchase_orders.md #38) -- the one
    place a Goods Receipt turns into an inventory movement, then renders
    and stores its A4 PDF (#41). One database transaction for the status
    flip, every line's received_quantity increment, the resulting stock
    movements, the PO status recompute and the PDF file record -- if any
    part fails, nothing is committed."""
    purchase_scope.require_permission(db, current_user, purchase_scope.RECEIVE)
    purchase_order = _get_po_in_org(db, purchase_order_id, current_user.organisation_id)
    receipt = _get_receipt_in_po(db, purchase_order.id, receipt_id)

    purchase_order_service.post_receipt(db, receipt=receipt, purchase_order=purchase_order, posted_by_user_id=current_user.id)

    receipt_lines = db.query(PurchaseOrderReceiptLine).filter(PurchaseOrderReceiptLine.receipt_id == receipt.id).order_by(PurchaseOrderReceiptLine.id).all()
    po_lines_by_id = {
        line.id: line
        for line in db.query(PurchaseOrderLine)
        .filter(PurchaseOrderLine.id.in_([rl.purchase_order_line_id for rl in receipt_lines]))
        .all()
    }
    materials_by_id = {
        m.id: m
        for m in db.query(RawMaterial).filter(RawMaterial.id.in_([rl.raw_material_id for rl in receipt_lines])).all()
    }
    unit_ids = [m.unit_of_measure_id for m in materials_by_id.values()]
    units_by_id = {u.id: u for u in db.query(UnitOfMeasure).filter(UnitOfMeasure.id.in_(unit_ids)).all()}
    supplier = db.query(Supplier).filter(Supplier.id == purchase_order.supplier_id).first()
    warehouse = db.query(Warehouse).filter(Warehouse.id == receipt.warehouse_id).first()
    organisation = db.query(Organisation).filter(Organisation.id == current_user.organisation_id).first()

    pdf_bytes = generate_purchase_order_receipt_pdf(
        PurchaseOrderReceiptPdfData(
            organisation_name=organisation.name,
            organisation_address=organisation.address,
            organisation_phone=organisation.contact_phone,
            organisation_email=organisation.contact_email,
            receipt_number=receipt.receipt_number,
            receipt_date=receipt.receipt_date,
            po_number=purchase_order.po_number,
            supplier_name=supplier.name,
            warehouse_name=warehouse.name,
            supplier_delivery_reference=receipt.supplier_delivery_reference,
            notes=receipt.notes,
            receiver_name=current_user.full_name,
            lines=[
                PurchaseOrderReceiptPdfLine(
                    material_name=materials_by_id[rl.raw_material_id].name if rl.raw_material_id in materials_by_id else f"#{rl.raw_material_id}",
                    ordered_quantity=po_lines_by_id[rl.purchase_order_line_id].quantity if rl.purchase_order_line_id in po_lines_by_id else Decimal("0"),
                    previously_received_quantity=(
                        po_lines_by_id[rl.purchase_order_line_id].received_quantity - rl.quantity
                        if rl.purchase_order_line_id in po_lines_by_id
                        else Decimal("0")
                    ),
                    received_quantity=rl.quantity,
                    unit_code=units_by_id[materials_by_id[rl.raw_material_id].unit_of_measure_id].code
                    if rl.raw_material_id in materials_by_id and materials_by_id[rl.raw_material_id].unit_of_measure_id in units_by_id
                    else None,
                )
                for rl in receipt_lines
            ],
            posted_at=receipt.posted_at,
        )
    )
    file_service.upload_file(
        db,
        organisation_id=current_user.organisation_id,
        uploaded_by_user_id=current_user.id,
        filename=f"{receipt.receipt_number}.pdf",
        stream=io.BytesIO(pdf_bytes),
        entity_type=_PURCHASE_ORDER_RECEIPT_ENTITY,
        entity_id=receipt.id,
    )

    audit_service.log_event(
        db,
        action=PURCHASE_ORDER_RECEIPT_POSTED,
        module=PROCUREMENT_MODULE,
        organisation_id=current_user.organisation_id,
        actor_user_id=current_user.id,
        entity_type=_PURCHASE_ORDER_ENTITY,
        entity_id=purchase_order.id,
        result="success",
        details=f"receipt_number: {receipt.receipt_number}, status: {purchase_order.status}",
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    db.refresh(purchase_order)
    return _build_po_out(db, purchase_order)


@router.post("/{purchase_order_id}/receipts/{receipt_id}/cancel", response_model=PurchaseOrderOut)
def cancel_receipt(
    purchase_order_id: int,
    receipt_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PurchaseOrderOut:
    """`draft -> cancelled` (docs/modules/purchase_orders.md #38) -- a
    receipt discarded before posting; never had any inventory effect."""
    purchase_scope.require_permission(db, current_user, purchase_scope.RECEIVE)
    purchase_order = _get_po_in_org(db, purchase_order_id, current_user.organisation_id)
    receipt = _get_receipt_in_po(db, purchase_order.id, receipt_id)

    purchase_order_service.cancel_receipt(db, receipt=receipt, cancelled_by_user_id=current_user.id)

    audit_service.log_event(
        db,
        action=PURCHASE_ORDER_RECEIPT_CANCELLED,
        module=PROCUREMENT_MODULE,
        organisation_id=current_user.organisation_id,
        actor_user_id=current_user.id,
        entity_type=_PURCHASE_ORDER_ENTITY,
        entity_id=purchase_order.id,
        result="success",
        details=f"receipt_number: {receipt.receipt_number}",
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    db.refresh(purchase_order)
    return _build_po_out(db, purchase_order)


@router.post("/{purchase_order_id}/receipts/{receipt_id}/reverse", response_model=PurchaseOrderOut)
def reverse_receipt(
    purchase_order_id: int,
    receipt_id: int,
    payload: ReverseReceiptRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PurchaseOrderOut:
    """`posted -> reversed` (docs/modules/purchase_orders.md #38) -- the
    only way to correct a posted receipt; never a direct edit of its
    quantities. The original receipt stays visible with its original
    values."""
    purchase_scope.require_permission(db, current_user, purchase_scope.RECEIVE)
    purchase_order = _get_po_in_org(db, purchase_order_id, current_user.organisation_id)
    receipt = _get_receipt_in_po(db, purchase_order.id, receipt_id)

    purchase_order_service.reverse_receipt(
        db, receipt=receipt, purchase_order=purchase_order, reason=payload.reason, reversed_by_user_id=current_user.id
    )

    audit_service.log_event(
        db,
        action=PURCHASE_ORDER_RECEIPT_REVERSED,
        module=PROCUREMENT_MODULE,
        organisation_id=current_user.organisation_id,
        actor_user_id=current_user.id,
        entity_type=_PURCHASE_ORDER_ENTITY,
        entity_id=purchase_order.id,
        result="success",
        details=f"receipt_number: {receipt.receipt_number}, reason: {payload.reason}",
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    db.refresh(purchase_order)
    return _build_po_out(db, purchase_order)


@router.post("/{purchase_order_id}/payments", response_model=PurchaseOrderOut, status_code=status.HTTP_201_CREATED)
def record_payment(
    purchase_order_id: int,
    payload: RecordPaymentRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PurchaseOrderOut:
    """docs/modules/purchase_orders.md #33 -- gated by the separate
    `purchase_payment` permission module (#34), not `purchase`, so an
    Accounts/Finance grant is independent of Procurement's own. Payment
    and receipt are fully independent transactions (#35) -- this never
    touches stock_movements/raw_material_inventory."""
    purchase_payment_scope.require_permission(db, current_user, purchase_payment_scope.CREATE)
    purchase_order = _get_po_in_org(db, purchase_order_id, current_user.organisation_id)

    lines = db.query(PurchaseOrderLine).filter(PurchaseOrderLine.purchase_order_id == purchase_order.id).all()
    existing_payments = (
        db.query(PurchaseOrderPayment).filter(PurchaseOrderPayment.purchase_order_id == purchase_order.id).all()
    )
    payment = purchase_order_service.record_payment(
        db,
        purchase_order=purchase_order,
        current_lines=lines,
        existing_payments=existing_payments,
        payment_date=payload.payment_date,
        amount=payload.amount,
        payment_method=payload.payment_method,
        reference_number=payload.reference_number,
        notes=payload.notes,
        created_by_user_id=current_user.id,
    )
    if payload.file_ids:
        file_service.attach_files(
            db,
            file_ids=payload.file_ids,
            entity_type=_PURCHASE_ORDER_PAYMENT_ENTITY,
            entity_id=payment.id,
            organisation_id=current_user.organisation_id,
        )

    audit_service.log_event(
        db,
        action=PURCHASE_ORDER_PAYMENT_RECORDED,
        module=PROCUREMENT_MODULE,
        organisation_id=current_user.organisation_id,
        actor_user_id=current_user.id,
        entity_type=_PURCHASE_ORDER_ENTITY,
        entity_id=purchase_order.id,
        result="success",
        details=f"payment_number: {payment.payment_number}, amount: {payment.amount}",
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    db.refresh(purchase_order)
    return _build_po_out(db, purchase_order)


@router.post("/{purchase_order_id}/payments/{payment_id}/cancel", response_model=PurchaseOrderOut)
def cancel_payment(
    purchase_order_id: int,
    payment_id: int,
    payload: CancelPaymentRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PurchaseOrderOut:
    """docs/modules/purchase_orders.md #33 -- never a hard delete; the
    payment stays visible in history with its original amount, simply
    excluded from paid_amount going forward."""
    purchase_payment_scope.require_permission(db, current_user, purchase_payment_scope.CANCEL)
    purchase_order = _get_po_in_org(db, purchase_order_id, current_user.organisation_id)
    payment = _get_payment_in_po(db, purchase_order.id, payment_id)

    purchase_order_service.cancel_payment(db, payment=payment, reason=payload.reason, cancelled_by_user_id=current_user.id)

    audit_service.log_event(
        db,
        action=PURCHASE_ORDER_PAYMENT_CANCELLED,
        module=PROCUREMENT_MODULE,
        organisation_id=current_user.organisation_id,
        actor_user_id=current_user.id,
        entity_type=_PURCHASE_ORDER_ENTITY,
        entity_id=purchase_order.id,
        result="success",
        details=f"payment_number: {payment.payment_number}, reason: {payload.reason}",
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    db.refresh(purchase_order)
    return _build_po_out(db, purchase_order)


def _check_purchase_order_file_access(db: Session, user: User, purchase_order_id: int) -> bool:
    """Registered against entity_type="purchase_order" -- confirmation
    evidence and other ad-hoc documents inherit the PO's own access rules
    (docs/modules/file_storage.md #5)."""
    purchase_order = db.query(PurchaseOrder).filter(PurchaseOrder.id == purchase_order_id).first()
    if purchase_order is None or purchase_order.organisation_id != user.organisation_id:
        return False
    return purchase_scope.can_perform(db, user, purchase_scope.VIEW)


def _check_purchase_order_revision_file_access(db: Session, user: User, revision_id: int) -> bool:
    """Registered against entity_type="purchase_order_revision" -- a
    revision's generated PDF inherits its owning PO's access rules."""
    revision = db.query(PurchaseOrderRevision).filter(PurchaseOrderRevision.id == revision_id).first()
    if revision is None:
        return False
    purchase_order = db.query(PurchaseOrder).filter(PurchaseOrder.id == revision.purchase_order_id).first()
    if purchase_order is None or purchase_order.organisation_id != user.organisation_id:
        return False
    return purchase_scope.can_perform(db, user, purchase_scope.VIEW)


def _check_purchase_order_payment_file_access(db: Session, user: User, payment_id: int) -> bool:
    """Registered against entity_type="purchase_order_payment" -- a
    payment's evidence inherits its owning PO's access rules."""
    payment = db.query(PurchaseOrderPayment).filter(PurchaseOrderPayment.id == payment_id).first()
    if payment is None or payment.organisation_id != user.organisation_id:
        return False
    return purchase_scope.can_perform(db, user, purchase_scope.VIEW)


def _check_purchase_order_receipt_file_access(db: Session, user: User, receipt_id: int) -> bool:
    """Registered against entity_type="purchase_order_receipt" -- a
    receipt's supplier evidence and generated PDF both inherit its owning
    PO's access rules."""
    receipt = db.query(PurchaseOrderReceipt).filter(PurchaseOrderReceipt.id == receipt_id).first()
    if receipt is None or receipt.organisation_id != user.organisation_id:
        return False
    return purchase_scope.can_perform(db, user, purchase_scope.VIEW)


register_entity_access_check(_PURCHASE_ORDER_ENTITY, _check_purchase_order_file_access)
register_entity_access_check(_PURCHASE_ORDER_REVISION_ENTITY, _check_purchase_order_revision_file_access)
register_entity_access_check(_PURCHASE_ORDER_PAYMENT_ENTITY, _check_purchase_order_payment_file_access)
register_entity_access_check(_PURCHASE_ORDER_RECEIPT_ENTITY, _check_purchase_order_receipt_file_access)
