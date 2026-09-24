import io
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.entity_access import register_entity_access_check
from app.core.errors import AccessDeniedError, BusinessRuleError, NotFoundError, ValidationError
from app.core.roles import ADMIN_ROLES
from app.core.list_query import apply_sort, paginate
from app.core.search import apply_keyword_filter
from app.core.storage import default_storage
from app.models.audit_event import (
    PROCUREMENT_MODULE,
    PURCHASE_ORDER_APPROVED,
    PURCHASE_ORDER_CREATED,
    PURCHASE_ORDER_FOLLOW_UP,
    PURCHASE_ORDER_LINE_ADDED,
    PURCHASE_ORDER_LINE_REMOVED,
    PURCHASE_ORDER_LINE_UPDATED,
    PURCHASE_ORDER_PAYMENT_CANCELLED,
    PURCHASE_ORDER_PAYMENT_RECORDED,
    PURCHASE_ORDER_RECEIPT_CANCELLED,
    PURCHASE_ORDER_RECEIPT_CREATED,
    PURCHASE_ORDER_RECEIPT_POSTED,
    PURCHASE_ORDER_RECEIPT_REVERSED,
    PURCHASE_ORDER_RECONCILED,
    PURCHASE_ORDER_SEND_FAILED,
    PURCHASE_ORDER_SENT,
    PURCHASE_ORDER_STATUS_CHANGED,
    PURCHASE_ORDER_SUBMITTED,
    PURCHASE_ORDER_UPDATED,
)
from app.models.file import FileRecord
from app.models.organisation import Organisation
from app.models.purchase_order import (
    APPROVED,
    CANCELLED,
    CLOSED,
    COMMUNICATION_FAILED,
    COMMUNICATION_FOLLOW_UP,
    COMMUNICATION_NOTE,
    COMMUNICATION_PO_SENT,
    COMMUNICATION_RECORDED,
    COMMUNICATION_SENT,
    DRAFT,
    SENT,
    PurchaseOrderCommunication,
    PurchaseOrderReconciliation,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderPayment,
    PurchaseOrderReceipt,
    PurchaseOrderReceiptLine,
    PurchaseOrderRevision,
    PurchaseOrderRevisionLine,
)
from app.models.raw_material import RawMaterial
from app.models.rfq import Rfq
from app.models.supplier import Supplier
from app.models.unit import UnitOfMeasure
from app.models.user import User
from app.schemas.file import FileOut
from app.schemas.purchase_order import (
    CancelPaymentRequest,
    CreateReceiptRequest,
    FollowUpRequest,
    PurchaseOrderCommunicationOut,
    PurchaseOrderReconciliationOut,
    ResolveReconciliationRequest,
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
    SendPurchaseOrderRequest,
)
from app.schemas.pagination import PaginatedResponse
from app.services import (
    audit_service,
    email_service,
    file_service,
    purchase_order_service,
    purchase_payment_scope,
    purchase_scope,
    uom_conversion,
)
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
_PURCHASE_ORDER_COMMUNICATION_ENTITY = "purchase_order_communication"


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


def _require_creator_or_admin(user: User, purchase_order: PurchaseOrder) -> None:
    """Discrepancies go back to the PO's creator -- only they (or an
    admin) resolve them."""
    if user.role not in ADMIN_ROLES and user.id != purchase_order.created_by_user_id:
        raise AccessDeniedError("Only the purchase order's creator can resolve its discrepancies.")


def _log_communication(
    db: Session,
    *,
    purchase_order: PurchaseOrder,
    user: User,
    kind: str,
    status: str,
    recipient: str | None = None,
    subject: str | None = None,
    message: str | None = None,
    error: str | None = None,
) -> PurchaseOrderCommunication:
    entry = PurchaseOrderCommunication(
        purchase_order_id=purchase_order.id,
        kind=kind,
        recipient=recipient,
        subject=subject,
        message=message,
        status=status,
        error=error,
        sent_by_user_id=user.id,
    )
    db.add(entry)
    db.flush()
    return entry


def _require_draft(purchase_order: PurchaseOrder) -> None:
    if purchase_order.status != DRAFT:
        raise BusinessRuleError("Only a draft purchase order can be edited.")


def _resolve_purchase_unit(db: Session, material: RawMaterial, unit_id: int | None, organisation_id: int) -> tuple[int, Decimal]:
    """(unit_of_measure_id, conversion_factor) for a PO line. No unit ->
    the material's own unit. Another unit must be active, in this
    organisation, and convert to the material's unit -- so receiving can
    always post stock in the material's unit."""
    if unit_id is None or unit_id == material.unit_of_measure_id:
        return material.unit_of_measure_id, Decimal(1)
    ids = [unit_id, material.unit_of_measure_id]
    if material.alternate_conversion_unit_of_measure_id:
        ids.append(material.alternate_conversion_unit_of_measure_id)
    units = {
        u.id: u
        for u in db.query(UnitOfMeasure).filter(UnitOfMeasure.id.in_(ids), UnitOfMeasure.organisation_id == organisation_id)
    }
    unit = units.get(unit_id)
    if unit is None or not unit.is_active:
        raise ValidationError(
            "unit_of_measure_id must be an active unit in your organisation.",
            fields={"unit_of_measure_id": "Not a valid active unit."},
        )
    ratio = uom_conversion.resolve_conversion_ratio(
        unit, units[material.unit_of_measure_id], material, units.get(material.alternate_conversion_unit_of_measure_id)
    )
    if ratio is None:
        raise ValidationError(
            f"{material.name} cannot be ordered in {unit.code} -- there is no conversion to its unit "
            f"{units[material.unit_of_measure_id].code}.",
            fields={"unit_of_measure_id": "No conversion to the material's unit."},
        )
    return unit.id, ratio


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


def days_late(receipt_date, expected_delivery_date) -> int:
    """Shown on every receipt; never blocks it."""
    if expected_delivery_date is None or receipt_date <= expected_delivery_date:
        return 0
    return (receipt_date - expected_delivery_date).days


def _build_receipt_out(db: Session, receipt: PurchaseOrderReceipt, purchase_order: PurchaseOrder) -> PurchaseOrderReceiptOut:
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
    out.days_late = days_late(receipt.receipt_date, purchase_order.expected_delivery_date)
    if receipt.posted_by_user_id or receipt.created_by_user_id:
        out.received_by_name = db.query(User.full_name).filter(
            User.id == (receipt.posted_by_user_id or receipt.created_by_user_id)
        ).scalar()
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
    total = purchase_order_service.total_amount(lines)
    final = purchase_order_service.final_amount(purchase_order, lines)
    paid = purchase_order_service.paid_amount(payments)
    reconciliations = (
        db.query(PurchaseOrderReconciliation)
        .filter(PurchaseOrderReconciliation.purchase_order_id == purchase_order.id)
        .order_by(PurchaseOrderReconciliation.id)
        .all()
    )
    communications = (
        db.query(PurchaseOrderCommunication)
        .filter(PurchaseOrderCommunication.purchase_order_id == purchase_order.id)
        .order_by(PurchaseOrderCommunication.id)
        .all()
    )
    communication_files: dict[int, list[FileRecord]] = {}
    if communications:
        for record in (
            db.query(FileRecord)
            .filter(
                FileRecord.entity_type == _PURCHASE_ORDER_COMMUNICATION_ENTITY,
                FileRecord.entity_id.in_([c.id for c in communications]),
                FileRecord.deleted_at.is_(None),
            )
            .order_by(FileRecord.id)
        ):
            communication_files.setdefault(record.entity_id, []).append(record)
    stamp_ids = {
        user_id
        for user_id in (
            purchase_order.created_by_user_id,
            purchase_order.approved_by_user_id,
            purchase_order.sent_by_user_id,
            purchase_order.cancelled_by_user_id,
            *(rec.resolved_by_user_id for rec in reconciliations),
            *(entry.sent_by_user_id for entry in communications),
        )
        if user_id
    }
    names = dict(db.query(User.id, User.full_name).filter(User.id.in_(stamp_ids)).all()) if stamp_ids else {}
    rfq_number = (
        db.query(Rfq.rfq_number).filter(Rfq.id == purchase_order.rfq_id).scalar() if purchase_order.rfq_id else None
    )
    return PurchaseOrderOut(
        id=purchase_order.id,
        organisation_id=purchase_order.organisation_id,
        po_number=purchase_order.po_number,
        supplier_id=purchase_order.supplier_id,
        warehouse_id=purchase_order.warehouse_id,
        rfq_id=purchase_order.rfq_id,
        rfq_number=rfq_number,
        rfq_response_id=purchase_order.rfq_response_id,
        status=purchase_order.status,
        revision_number=purchase_order.revision_number,
        order_date=purchase_order.order_date,
        expected_delivery_date=purchase_order.expected_delivery_date,
        supplier_reference=purchase_order.supplier_reference,
        payment_terms=purchase_order.payment_terms,
        currency=purchase_order.currency,
        delivery_instructions=purchase_order.delivery_instructions,
        notes=purchase_order.notes,
        cancel_reason=purchase_order.cancel_reason,
        created_at=purchase_order.created_at,
        created_by_user_id=purchase_order.created_by_user_id,
        approved_at=purchase_order.approved_at,
        approved_by_user_id=purchase_order.approved_by_user_id,
        sent_at=purchase_order.sent_at,
        sent_by_user_id=purchase_order.sent_by_user_id,
        cancelled_at=purchase_order.cancelled_at,
        cancelled_by_user_id=purchase_order.cancelled_by_user_id,
        created_by_name=names.get(purchase_order.created_by_user_id),
        approved_by_name=names.get(purchase_order.approved_by_user_id),
        sent_by_name=names.get(purchase_order.sent_by_user_id),
        cancelled_by_name=names.get(purchase_order.cancelled_by_user_id),
        total_amount=total,
        amount_adjustment=purchase_order.amount_adjustment,
        final_amount=final,
        paid_amount=paid,
        outstanding_amount=final - paid,
        payment_status=purchase_order_service.payment_status(final, paid),
        lines=[PurchaseOrderLineOut.model_validate(line) for line in lines],
        revisions=[_build_revision_out(db, revision) for revision in revisions],
        documents=[FileOut.model_validate(f) for f in documents],
        payments=[_build_payment_out(db, payment) for payment in payments],
        receipts=[_build_receipt_out(db, receipt, purchase_order) for receipt in receipts],
        reconciliations=[
            PurchaseOrderReconciliationOut.model_validate(rec).model_copy(
                update={"resolved_by_name": names.get(rec.resolved_by_user_id)}
            )
            for rec in reconciliations
        ],
        communications=[
            PurchaseOrderCommunicationOut.model_validate(entry).model_copy(
                update={
                    "sent_by_name": names.get(entry.sent_by_user_id),
                    "files": [FileOut.model_validate(f) for f in communication_files.get(entry.id, [])],
                }
            )
            for entry in communications
        ],
    )


def store_receipt_pdf(db: Session, purchase_order: PurchaseOrder, receipt: PurchaseOrderReceipt, current_user: User) -> None:
    """Renders and stores a posted receipt's A4 PDF (no prices) -- shared
    by this module and app/api/goods_receiving.py. upload_file commits."""
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
    # Receipts are counted in the PO line's purchase unit.
    unit_ids = [line.unit_of_measure_id for line in po_lines_by_id.values()]
    units_by_id = {u.id: u for u in db.query(UnitOfMeasure).filter(UnitOfMeasure.id.in_(unit_ids)).all()}
    supplier = db.query(Supplier).filter(Supplier.id == purchase_order.supplier_id).first()
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
                    unit_code=units_by_id[po_lines_by_id[rl.purchase_order_line_id].unit_of_measure_id].code
                    if rl.purchase_order_line_id in po_lines_by_id
                    and po_lines_by_id[rl.purchase_order_line_id].unit_of_measure_id in units_by_id
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
    """Always starts `draft` with no items -- items are added via
    POST .../lines (docs/modules/purchase_orders.md #2/#3). PO date is
    today; `rfq_id` is only ever set by the RFQ's PO-generation step."""
    purchase_scope.require_permission(db, current_user, purchase_scope.CREATE)
    _resolve_active_supplier(db, payload.supplier_id, current_user.organisation_id)
    if payload.expected_delivery_date < date.today():
        raise ValidationError(
            "Expected delivery date cannot be in the past.", fields={"expected_delivery_date": "Cannot be in the past."}
        )

    purchase_order = purchase_order_service.create_purchase_order_with_lines(
        db,
        organisation_id=current_user.organisation_id,
        supplier_id=payload.supplier_id,
        order_date=date.today(),
        expected_delivery_date=payload.expected_delivery_date,
        payment_terms=payload.payment_terms,
        supplier_reference=payload.supplier_reference,
        delivery_instructions=payload.delivery_instructions,
        notes=payload.notes,
        created_by_user_id=current_user.id,
        lines=[],
    )

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
    supplier_id/rfq_id are immutable and have no update path
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
    """Draft-only. Material, quantity, purchase unit (default: the
    material's own) and agreed unit price are required; `line_total` is
    computed and snapshotted (docs/modules/purchase_orders.md #3)."""
    purchase_scope.require_permission(db, current_user, purchase_scope.CREATE)
    purchase_order = _get_po_in_org(db, purchase_order_id, current_user.organisation_id)
    _require_draft(purchase_order)
    material = _resolve_active_raw_material(db, payload.raw_material_id, current_user.organisation_id)
    unit_id, factor = _resolve_purchase_unit(db, material, payload.unit_of_measure_id, current_user.organisation_id)

    line = PurchaseOrderLine(
        purchase_order_id=purchase_order.id,
        raw_material_id=payload.raw_material_id,
        quantity=payload.quantity,
        unit_of_measure_id=unit_id,
        conversion_factor=factor,
        unit_price=payload.unit_price,
        line_total=purchase_order_service.compute_line_total(payload.quantity, payload.unit_price),
        required_by_date=payload.required_by_date,
        remarks=payload.remarks,
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
    if "unit_of_measure_id" in updates:
        material = _resolve_active_raw_material(db, line.raw_material_id, current_user.organisation_id)
        line.unit_of_measure_id, line.conversion_factor = _resolve_purchase_unit(
            db, material, updates["unit_of_measure_id"], current_user.organisation_id
        )
    for field in ("required_by_date", "remarks"):
        if field in updates:
            setattr(line, field, updates[field])
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
    """Back to `draft` (send a pending PO back, or "Create Revision" of an
    approved/sent PO -- it must then be approved again) or cancel
    (docs/modules/purchase_orders.md #23)."""
    purchase_scope.require_permission(db, current_user, purchase_scope.ISSUE)
    purchase_order = _get_po_in_org(db, purchase_order_id, current_user.organisation_id)
    purchase_order_service.assert_transition_allowed(purchase_order.status, payload.status)

    before_status = purchase_order.status
    purchase_order.status = payload.status
    if payload.status == CANCELLED:
        purchase_order.cancel_reason = payload.cancel_reason
        purchase_order.cancelled_at = datetime.utcnow()
        purchase_order.cancelled_by_user_id = current_user.id
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


@router.post("/{purchase_order_id}/submit", response_model=PurchaseOrderOut)
def submit_purchase_order(
    purchase_order_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PurchaseOrderOut:
    """`draft -> pending_approval` (docs/modules/purchase_orders.md #23)."""
    purchase_scope.require_permission(db, current_user, purchase_scope.CREATE)
    purchase_order = _get_po_in_org(db, purchase_order_id, current_user.organisation_id)
    purchase_order_service.submit_for_approval(db, purchase_order=purchase_order)
    audit_service.log_event(
        db,
        action=PURCHASE_ORDER_SUBMITTED,
        module=PROCUREMENT_MODULE,
        organisation_id=current_user.organisation_id,
        actor_user_id=current_user.id,
        entity_type=_PURCHASE_ORDER_ENTITY,
        entity_id=purchase_order.id,
        result="success",
        details="status: draft -> pending_approval",
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    db.refresh(purchase_order)
    return _build_po_out(db, purchase_order)


@router.post("/{purchase_order_id}/approve", response_model=PurchaseOrderOut)
def approve_purchase_order(
    purchase_order_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PurchaseOrderOut:
    """`pending_approval -> approved` (docs/modules/purchase_orders.md
    #23/#24/#27): snapshots the current header/items into a new immutable
    revision and renders its official PDF -- never regenerated later.
    One commit for all of it."""
    purchase_scope.require_permission(db, current_user, purchase_scope.APPROVE)
    purchase_order = _get_po_in_org(db, purchase_order_id, current_user.organisation_id)
    supplier = _resolve_active_supplier(db, purchase_order.supplier_id, current_user.organisation_id)

    revision = purchase_order_service.approve_purchase_order(db, purchase_order=purchase_order, approved_by_user_id=current_user.id)

    revision_lines = (
        db.query(PurchaseOrderRevisionLine).filter(PurchaseOrderRevisionLine.revision_id == revision.id).order_by(PurchaseOrderRevisionLine.id).all()
    )
    materials_by_id = {
        m.id: m
        for m in db.query(RawMaterial).filter(RawMaterial.id.in_([line.raw_material_id for line in revision_lines])).all()
    }
    units_by_id = {
        u.id: u
        for u in db.query(UnitOfMeasure).filter(UnitOfMeasure.id.in_([line.unit_of_measure_id for line in revision_lines])).all()
    }
    organisation = db.query(Organisation).filter(Organisation.id == current_user.organisation_id).first()
    rfq_number = db.query(Rfq.rfq_number).filter(Rfq.id == purchase_order.rfq_id).scalar() if purchase_order.rfq_id else None

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
                    unit_code=units_by_id[line.unit_of_measure_id].code if line.unit_of_measure_id in units_by_id else "",
                    remarks=line.remarks,
                )
                for line in revision_lines
            ],
            total_amount=revision.total_amount,
            issued_at=revision.issued_at,
            currency=purchase_order.currency,
            delivery_instructions=purchase_order.delivery_instructions,
            rfq_reference=rfq_number,
            approved_by=current_user.full_name,
        )
    )
    audit_service.log_event(
        db,
        action=PURCHASE_ORDER_APPROVED,
        module=PROCUREMENT_MODULE,
        organisation_id=current_user.organisation_id,
        actor_user_id=current_user.id,
        entity_type=_PURCHASE_ORDER_ENTITY,
        entity_id=purchase_order.id,
        result="success",
        details=f"revision: {revision.revision_number}, total_amount: {revision.total_amount} {purchase_order.currency}",
        ip_address=request.client.host if request.client else None,
    )
    # upload_file commits -- the single commit point for the revision,
    # its lines, the status flip, the audit event and the PDF record.
    file_service.upload_file(
        db,
        organisation_id=current_user.organisation_id,
        uploaded_by_user_id=current_user.id,
        filename=f"{purchase_order.po_number}-Rev{revision.revision_number}.pdf",
        stream=io.BytesIO(pdf_bytes),
        entity_type=_PURCHASE_ORDER_REVISION_ENTITY,
        entity_id=revision.id,
    )
    db.refresh(purchase_order)
    return _build_po_out(db, purchase_order)


@router.post("/{purchase_order_id}/send", response_model=PurchaseOrderOut)
def send_purchase_order(
    purchase_order_id: int,
    payload: SendPurchaseOrderRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PurchaseOrderOut:
    """`approved -> sent`. `email=true` emails the approved revision's
    immutable PDF to the supplier (also re-sends an already-sent PO);
    `email=false` records it was sent another way
    (docs/modules/purchase_orders.md #27). A
    failed send is recorded and re-raised before anything is marked
    successfully sent (the same immediate-commit-on-failure pattern
    app/services/auth_service.py's login lockout counter already
    established for a "must persist even though we're about to error"
    case)."""
    purchase_scope.require_permission(db, current_user, purchase_scope.SEND)
    purchase_order = _get_po_in_org(db, purchase_order_id, current_user.organisation_id)
    if purchase_order.status not in (APPROVED, SENT):
        raise BusinessRuleError("Only an approved purchase order can be sent.")
    if purchase_order.status == SENT and not payload.email:
        raise BusinessRuleError("This purchase order is already marked as sent.")

    if not payload.email:
        purchase_order_service.mark_sent(purchase_order, sent_by_user_id=current_user.id)
        db.add(purchase_order)
        _log_communication(
            db, purchase_order=purchase_order, user=current_user, kind=COMMUNICATION_PO_SENT, status=COMMUNICATION_RECORDED,
            message=f"PO revision {purchase_order.revision_number} sent to supplier (not by email).",
        )
        audit_service.log_event(
            db,
            action=PURCHASE_ORDER_SENT,
            module=PROCUREMENT_MODULE,
            organisation_id=current_user.organisation_id,
            actor_user_id=current_user.id,
            entity_type=_PURCHASE_ORDER_ENTITY,
            entity_id=purchase_order.id,
            result="success",
            details=f"revision: {purchase_order.revision_number}, marked sent (not emailed)",
            ip_address=request.client.host if request.client else None,
        )
        db.commit()
        db.refresh(purchase_order)
        return _build_po_out(db, purchase_order)

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
        _log_communication(
            db, purchase_order=purchase_order, user=current_user, kind=COMMUNICATION_PO_SENT, status=COMMUNICATION_FAILED,
            recipient=supplier.email, subject=subject, message=body, error=exc.message,
        )
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

    if purchase_order.status == APPROVED:
        purchase_order_service.mark_sent(purchase_order, sent_by_user_id=current_user.id)
        db.add(purchase_order)
    _log_communication(
        db, purchase_order=purchase_order, user=current_user, kind=COMMUNICATION_PO_SENT, status=COMMUNICATION_SENT,
        recipient=supplier.email, subject=subject, message=body,
    )
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
    # Returns full commercial data -- purchasing users only. The
    # warehouse uses app/api/goods_receiving.py, which never exposes prices.
    purchase_scope.require_permission(db, current_user, purchase_scope.VIEW)
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
        remarks={line.purchase_order_line_id: line.remarks for line in payload.lines},
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
    # Returns full commercial data -- purchasing users only. The
    # warehouse uses app/api/goods_receiving.py, which never exposes prices.
    purchase_scope.require_permission(db, current_user, purchase_scope.VIEW)
    purchase_order = _get_po_in_org(db, purchase_order_id, current_user.organisation_id)
    receipt = _get_receipt_in_po(db, purchase_order.id, receipt_id)

    purchase_order_service.post_receipt(db, receipt=receipt, purchase_order=purchase_order, posted_by_user_id=current_user.id)

    # upload_file commits: the receipt, stock movements, status and PDF
    # land together.
    store_receipt_pdf(db, purchase_order, receipt, current_user)

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
    # Returns full commercial data -- purchasing users only. The
    # warehouse uses app/api/goods_receiving.py, which never exposes prices.
    purchase_scope.require_permission(db, current_user, purchase_scope.VIEW)
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
    # Returns full commercial data -- purchasing users only. The
    # warehouse uses app/api/goods_receiving.py, which never exposes prices.
    purchase_scope.require_permission(db, current_user, purchase_scope.VIEW)
    purchase_order = _get_po_in_org(db, purchase_order_id, current_user.organisation_id)
    receipt = _get_receipt_in_po(db, purchase_order.id, receipt_id)
    if purchase_order.status == CLOSED:
        raise BusinessRuleError("A closed purchase order can't be changed.")

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
        is_final=payload.is_final,
    )
    purchase_order_service.check_payment_discrepancy(db, purchase_order, final_payment=payload.is_final)
    purchase_order_service.refresh_status(db, purchase_order)
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
        details=f"payment_number: {payment.payment_number}, amount: {payment.amount}, final: {payment.is_final}, "
        f"po status: {purchase_order.status}",
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
    if purchase_order.status == CLOSED:
        raise BusinessRuleError("A closed purchase order can't be changed.")

    purchase_order_service.cancel_payment(db, payment=payment, reason=payload.reason, cancelled_by_user_id=current_user.id)
    db.flush()
    purchase_order_service.refresh_status(db, purchase_order)

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


@router.post("/{purchase_order_id}/reconciliations/{reconciliation_id}/resolve", response_model=PurchaseOrderOut)
def resolve_reconciliation(
    purchase_order_id: int,
    reconciliation_id: int,
    payload: ResolveReconciliationRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PurchaseOrderOut:
    """The PO creator's documented decision on a receipt or payment
    discrepancy (docs/modules/purchase_orders.md Revision 6)."""
    purchase_scope.require_permission(db, current_user, purchase_scope.VIEW)
    purchase_order = _get_po_in_org(db, purchase_order_id, current_user.organisation_id)
    _require_creator_or_admin(current_user, purchase_order)
    reconciliation = (
        db.query(PurchaseOrderReconciliation)
        .filter(
            PurchaseOrderReconciliation.id == reconciliation_id,
            PurchaseOrderReconciliation.purchase_order_id == purchase_order.id,
        )
        .first()
    )
    if reconciliation is None:
        raise NotFoundError("Discrepancy not found.")

    purchase_order_service.resolve_reconciliation(
        db,
        purchase_order=purchase_order,
        reconciliation=reconciliation,
        resolution=payload.resolution,
        note=payload.note,
        resolved_by_user_id=current_user.id,
    )
    audit_service.log_event(
        db,
        action=PURCHASE_ORDER_RECONCILED,
        module=PROCUREMENT_MODULE,
        organisation_id=current_user.organisation_id,
        actor_user_id=current_user.id,
        entity_type=_PURCHASE_ORDER_ENTITY,
        entity_id=purchase_order.id,
        result="success",
        details=f"{reconciliation.kind}: {payload.resolution} -- {payload.note}; po status: {purchase_order.status}",
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    db.refresh(purchase_order)
    return _build_po_out(db, purchase_order)


_FOLLOW_UP_STATUSES = ("approved", "sent", "partially_received", "reconciliation_required", "received", "payment_reconciliation")


@router.post("/{purchase_order_id}/follow-ups", response_model=PurchaseOrderOut, status_code=status.HTTP_201_CREATED)
def follow_up(
    purchase_order_id: int,
    payload: FollowUpRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PurchaseOrderOut:
    """Supplier follow-up (docs/modules/purchase_orders.md Revision 6):
    email the supplier, or record their reply. Kept on the PO's own
    history -- no separate communication module. A failed email is kept
    on the history with its error and reported."""
    purchase_scope.require_permission(db, current_user, purchase_scope.SEND)
    purchase_order = _get_po_in_org(db, purchase_order_id, current_user.organisation_id)
    if purchase_order.status not in _FOLLOW_UP_STATUSES:
        raise BusinessRuleError("Follow-ups are only possible on an approved, open purchase order.")

    if not payload.send_email:
        entry = _log_communication(
            db, purchase_order=purchase_order, user=current_user, kind=COMMUNICATION_NOTE, status=COMMUNICATION_RECORDED,
            subject=payload.subject, message=payload.message,
        )
        if payload.file_ids:
            file_service.attach_files(
                db, file_ids=payload.file_ids, entity_type=_PURCHASE_ORDER_COMMUNICATION_ENTITY,
                entity_id=entry.id, organisation_id=current_user.organisation_id,
            )
    else:
        supplier = db.query(Supplier).filter(Supplier.id == purchase_order.supplier_id).one()
        if not supplier.email:
            raise ValidationError("This supplier has no email address on file.", fields={"supplier_id": "Missing email address."})
        subject = payload.subject or f"Follow-up: Purchase Order {purchase_order.po_number}"

        # One attachment per email (app/services/email_service.py): the PO
        # PDF if asked for, otherwise the first uploaded file.
        attachment: FileRecord | None = None
        if payload.attach_po_pdf:
            revision = (
                db.query(PurchaseOrderRevision)
                .filter(
                    PurchaseOrderRevision.purchase_order_id == purchase_order.id,
                    PurchaseOrderRevision.revision_number == purchase_order.revision_number,
                )
                .first()
            )
            if revision is not None:
                attachment = (
                    db.query(FileRecord)
                    .filter(
                        FileRecord.entity_type == _PURCHASE_ORDER_REVISION_ENTITY,
                        FileRecord.entity_id == revision.id,
                        FileRecord.deleted_at.is_(None),
                    )
                    .first()
                )
        entry = _log_communication(
            db, purchase_order=purchase_order, user=current_user, kind=COMMUNICATION_FOLLOW_UP, status=COMMUNICATION_SENT,
            recipient=supplier.email, subject=subject, message=payload.message,
        )
        if payload.file_ids:
            attached = file_service.attach_files(
                db, file_ids=payload.file_ids, entity_type=_PURCHASE_ORDER_COMMUNICATION_ENTITY,
                entity_id=entry.id, organisation_id=current_user.organisation_id,
            )
            if attachment is None and attached:
                attachment = attached[0]

        try:
            email_service.send_email(
                db,
                current_user.organisation_id,
                supplier.email,
                subject,
                payload.message,
                b"".join(default_storage.download(attachment.storage_key)) if attachment else None,
                attachment.original_filename if attachment else None,
            )
        except BusinessRuleError as exc:
            entry.status = COMMUNICATION_FAILED
            entry.error = exc.message
            db.add(entry)
            db.commit()
            raise

    audit_service.log_event(
        db,
        action=PURCHASE_ORDER_FOLLOW_UP,
        module=PROCUREMENT_MODULE,
        organisation_id=current_user.organisation_id,
        actor_user_id=current_user.id,
        entity_type=_PURCHASE_ORDER_ENTITY,
        entity_id=purchase_order.id,
        result="success",
        details=f"{'email to ' + entry.recipient if payload.send_email else 'supplier reply recorded'}",
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
    # Receipt documents carry no prices, so the warehouse (receive) can
    # open them too.
    return purchase_scope.can_perform(db, user, purchase_scope.VIEW) or purchase_scope.can_perform(
        db, user, purchase_scope.RECEIVE
    )


def _check_purchase_order_communication_file_access(db: Session, user: User, communication_id: int) -> bool:
    organisation_id = (
        db.query(PurchaseOrder.organisation_id)
        .join(PurchaseOrderCommunication, PurchaseOrderCommunication.purchase_order_id == PurchaseOrder.id)
        .filter(PurchaseOrderCommunication.id == communication_id)
        .scalar()
    )
    return organisation_id == user.organisation_id and purchase_scope.can_perform(db, user, purchase_scope.VIEW)


register_entity_access_check(_PURCHASE_ORDER_ENTITY, _check_purchase_order_file_access)
register_entity_access_check(_PURCHASE_ORDER_REVISION_ENTITY, _check_purchase_order_revision_file_access)
register_entity_access_check(_PURCHASE_ORDER_PAYMENT_ENTITY, _check_purchase_order_payment_file_access)
register_entity_access_check(_PURCHASE_ORDER_RECEIPT_ENTITY, _check_purchase_order_receipt_file_access)
register_entity_access_check(_PURCHASE_ORDER_COMMUNICATION_ENTITY, _check_purchase_order_communication_file_access)
