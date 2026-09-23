from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.entity_access import register_entity_access_check
from app.core.errors import BusinessRuleError, ConflictError, NotFoundError, ValidationError
from app.core.list_query import apply_sort, paginate
from app.core.search import apply_keyword_filter
from app.models.audit_event import (
    PROCUREMENT_MODULE,
    RFQ_CONVERTED,
    RFQ_CREATED,
    RFQ_DECIDED,
    RFQ_LINE_ADDED,
    RFQ_LINE_REMOVED,
    RFQ_LINE_UPDATED,
    RFQ_RESPONSE_CAPTURED,
    RFQ_STATUS_CHANGED,
    RFQ_UPDATED,
)
from app.models.file import FileRecord
from app.models.raw_material import RawMaterial
from app.models.rfq import CANCELLED, DRAFT, Rfq, RfqLine, RfqResponse
from app.models.supplier import Supplier
from app.models.user import User
from app.models.warehouse import Warehouse
from app.schemas.file import FileOut
from app.schemas.pagination import PaginatedResponse
from app.schemas.rfq import (
    RfqCaptureResponseRequest,
    RfqConvertRequest,
    RfqCreateRequest,
    RfqDecisionRequest,
    RfqLineCreateRequest,
    RfqLineOut,
    RfqLineUpdateRequest,
    RfqOut,
    RfqResponseOut,
    RfqStatusChangeRequest,
    RfqUpdateRequest,
)
from app.services import audit_service, file_service, rfq_scope, rfq_service

router = APIRouter(prefix="/api/rfqs", tags=["rfqs"])

_SORT_FIELDS = {
    "rfq_number": Rfq.rfq_number,
    "rfq_date": Rfq.rfq_date,
    "status": Rfq.status,
    "created_at": Rfq.created_at,
}

_MAX_CODE_ATTEMPTS = 5


def _get_rfq_in_org(db: Session, rfq_id: int, organisation_id: int) -> Rfq:
    rfq = db.query(Rfq).filter(Rfq.id == rfq_id, Rfq.organisation_id == organisation_id).first()
    if rfq is None:
        # 404 whether the id doesn't exist at all or belongs to another
        # organisation -- never confirm another organisation's RFQ id
        # (docs/modules/organisation.md #3).
        raise NotFoundError("RFQ not found.")
    return rfq


def _get_line_in_rfq(db: Session, rfq_id: int, line_id: int) -> RfqLine:
    line = db.query(RfqLine).filter(RfqLine.id == line_id, RfqLine.rfq_id == rfq_id).first()
    if line is None:
        raise NotFoundError("RFQ line not found.")
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


def _require_draft(rfq: Rfq) -> None:
    if rfq.status != DRAFT:
        raise BusinessRuleError("Only a draft RFQ can be edited.")


def _build_response_out(db: Session, response: RfqResponse) -> RfqResponseOut:
    files = (
        db.query(FileRecord)
        .filter(
            FileRecord.entity_type == "rfq_response",
            FileRecord.entity_id == response.id,
            FileRecord.deleted_at.is_(None),
        )
        .order_by(FileRecord.id)
        .all()
    )
    return RfqResponseOut(
        id=response.id,
        response_received_at=response.response_received_at,
        note=response.note,
        created_by_user_id=response.created_by_user_id,
        files=[FileOut.model_validate(f) for f in files],
    )


def _build_rfq_out(db: Session, rfq: Rfq) -> RfqOut:
    lines = db.query(RfqLine).filter(RfqLine.rfq_id == rfq.id).order_by(RfqLine.id).all()
    responses = db.query(RfqResponse).filter(RfqResponse.rfq_id == rfq.id).order_by(RfqResponse.id).all()
    return RfqOut(
        id=rfq.id,
        organisation_id=rfq.organisation_id,
        rfq_number=rfq.rfq_number,
        supplier_id=rfq.supplier_id,
        status=rfq.status,
        rfq_date=rfq.rfq_date,
        required_delivery_date=rfq.required_delivery_date,
        notes=rfq.notes,
        cancel_reason=rfq.cancel_reason,
        decided_by_user_id=rfq.decided_by_user_id,
        decided_at=rfq.decided_at,
        decision_note=rfq.decision_note,
        selected_response_id=rfq.selected_response_id,
        purchase_order_id=rfq.purchase_order_id,
        lines=[RfqLineOut.model_validate(line) for line in lines],
        responses=[_build_response_out(db, response) for response in responses],
    )


@router.get("", response_model=PaginatedResponse[RfqOut])
def list_rfqs(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    sort_by: str | None = Query(None),
    sort_direction: Literal["asc", "desc"] = Query("asc"),
    status_filter: str | None = Query(None, alias="status"),
    supplier_id: int | None = Query(None),
    q: str | None = Query(None, max_length=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PaginatedResponse[RfqOut]:
    rfq_scope.require_permission(db, current_user, rfq_scope.VIEW)

    query = db.query(Rfq).filter(Rfq.organisation_id == current_user.organisation_id)
    if status_filter is not None:
        query = query.filter(Rfq.status == status_filter)
    if supplier_id is not None:
        query = query.filter(Rfq.supplier_id == supplier_id)
    query = apply_keyword_filter(query, q, Rfq.rfq_number)
    query = apply_sort(query, sort_by, sort_direction, _SORT_FIELDS, default=Rfq.id)

    rfqs, pagination = paginate(query, page, page_size)
    return PaginatedResponse(data=[_build_rfq_out(db, rfq) for rfq in rfqs], pagination=pagination)


@router.get("/{rfq_id}", response_model=RfqOut)
def get_rfq(rfq_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> RfqOut:
    rfq_scope.require_permission(db, current_user, rfq_scope.VIEW)
    rfq = _get_rfq_in_org(db, rfq_id, current_user.organisation_id)
    return _build_rfq_out(db, rfq)


@router.post("", response_model=RfqOut, status_code=status.HTTP_201_CREATED)
def create_rfq(
    payload: RfqCreateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RfqOut:
    """Always starts `draft` and empty -- lines are added afterward via
    POST .../lines (docs/modules/rfq.md #2)."""
    rfq_scope.require_permission(db, current_user, rfq_scope.CREATE)
    _resolve_active_supplier(db, payload.supplier_id, current_user.organisation_id)

    rfq: Rfq | None = None
    last_error: IntegrityError | None = None
    for _ in range(_MAX_CODE_ATTEMPTS):
        rfq_number = rfq_service.generate_rfq_number(db, current_user.organisation_id)
        rfq = Rfq(
            organisation_id=current_user.organisation_id,
            rfq_number=rfq_number,
            supplier_id=payload.supplier_id,
            status=DRAFT,
            rfq_date=payload.rfq_date,
            required_delivery_date=payload.required_delivery_date,
            notes=payload.notes,
        )
        db.add(rfq)
        try:
            db.flush()
            last_error = None
            break
        except IntegrityError as exc:
            db.rollback()
            last_error = exc
    if last_error is not None or rfq is None:
        raise ConflictError("Could not generate a unique RFQ number. Please try again.") from last_error

    audit_service.log_event(
        db,
        action=RFQ_CREATED,
        module=PROCUREMENT_MODULE,
        organisation_id=current_user.organisation_id,
        actor_user_id=current_user.id,
        entity_type="rfq",
        entity_id=rfq.id,
        result="success",
        details=f"rfq_number: {rfq.rfq_number}, supplier_id: {rfq.supplier_id}",
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    db.refresh(rfq)
    return _build_rfq_out(db, rfq)


@router.patch("/{rfq_id}", response_model=RfqOut)
def update_rfq(
    rfq_id: int,
    payload: RfqUpdateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RfqOut:
    """Draft-only -- supplier_id is immutable and has no update path here."""
    rfq_scope.require_permission(db, current_user, rfq_scope.CREATE)
    rfq = _get_rfq_in_org(db, rfq_id, current_user.organisation_id)
    _require_draft(rfq)

    updates = payload.model_dump(exclude_unset=True)
    before = {field: getattr(rfq, field) for field in updates}
    for field, value in updates.items():
        setattr(rfq, field, value)
    db.add(rfq)
    db.flush()

    changes = audit_service.diff_fields(before, updates)
    if changes:
        audit_service.log_event(
            db,
            action=RFQ_UPDATED,
            module=PROCUREMENT_MODULE,
            organisation_id=current_user.organisation_id,
            actor_user_id=current_user.id,
            entity_type="rfq",
            entity_id=rfq.id,
            result="success",
            details=audit_service.format_changes(changes),
            ip_address=request.client.host if request.client else None,
        )
    db.commit()
    db.refresh(rfq)
    return _build_rfq_out(db, rfq)


@router.post("/{rfq_id}/lines", response_model=RfqOut, status_code=status.HTTP_201_CREATED)
def add_rfq_line(
    rfq_id: int,
    payload: RfqLineCreateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RfqOut:
    rfq_scope.require_permission(db, current_user, rfq_scope.CREATE)
    rfq = _get_rfq_in_org(db, rfq_id, current_user.organisation_id)
    _require_draft(rfq)
    material = _resolve_active_raw_material(db, payload.raw_material_id, current_user.organisation_id)

    line = RfqLine(rfq_id=rfq.id, raw_material_id=material.id, quantity=payload.quantity)
    db.add(line)
    db.flush()

    audit_service.log_event(
        db,
        action=RFQ_LINE_ADDED,
        module=PROCUREMENT_MODULE,
        organisation_id=current_user.organisation_id,
        actor_user_id=current_user.id,
        entity_type="rfq",
        entity_id=rfq.id,
        result="success",
        details=f"raw_material_id: {line.raw_material_id}, quantity: {line.quantity}",
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    db.refresh(rfq)
    return _build_rfq_out(db, rfq)


@router.patch("/{rfq_id}/lines/{line_id}", response_model=RfqOut)
def update_rfq_line(
    rfq_id: int,
    line_id: int,
    payload: RfqLineUpdateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RfqOut:
    rfq_scope.require_permission(db, current_user, rfq_scope.CREATE)
    rfq = _get_rfq_in_org(db, rfq_id, current_user.organisation_id)
    _require_draft(rfq)
    line = _get_line_in_rfq(db, rfq.id, line_id)

    line.quantity = payload.quantity
    db.add(line)
    db.flush()

    audit_service.log_event(
        db,
        action=RFQ_LINE_UPDATED,
        module=PROCUREMENT_MODULE,
        organisation_id=current_user.organisation_id,
        actor_user_id=current_user.id,
        entity_type="rfq",
        entity_id=rfq.id,
        result="success",
        details=f"line_id: {line.id}, quantity: {line.quantity}",
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    db.refresh(rfq)
    return _build_rfq_out(db, rfq)


@router.delete("/{rfq_id}/lines/{line_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_rfq_line(
    rfq_id: int,
    line_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    rfq_scope.require_permission(db, current_user, rfq_scope.CREATE)
    rfq = _get_rfq_in_org(db, rfq_id, current_user.organisation_id)
    _require_draft(rfq)
    line = _get_line_in_rfq(db, rfq.id, line_id)

    audit_service.log_event(
        db,
        action=RFQ_LINE_REMOVED,
        module=PROCUREMENT_MODULE,
        organisation_id=current_user.organisation_id,
        actor_user_id=current_user.id,
        entity_type="rfq",
        entity_id=rfq.id,
        result="success",
        details=f"raw_material_id: {line.raw_material_id}",
        ip_address=request.client.host if request.client else None,
    )
    db.delete(line)
    db.commit()


@router.patch("/{rfq_id}/status", response_model=RfqOut)
def change_rfq_status(
    rfq_id: int,
    payload: RfqStatusChangeRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RfqOut:
    """Issue or cancel (docs/modules/rfq.md #3/#4) -- gated by the
    "issue" RFQ permission, which covers both lifecycle decisions, the
    same "one action covers confirm+cancel" shape
    docs/modules/purchase_orders.md #13 already established. Issuing
    requires at least one line."""
    rfq_scope.require_permission(db, current_user, rfq_scope.ISSUE)
    rfq = _get_rfq_in_org(db, rfq_id, current_user.organisation_id)
    rfq_service.assert_transition_allowed(rfq.status, payload.status)

    if payload.status != CANCELLED:
        has_line = db.query(RfqLine.id).filter(RfqLine.rfq_id == rfq.id).first() is not None
        if not has_line:
            raise BusinessRuleError("Cannot issue an RFQ with no lines.")

    before_status = rfq.status
    rfq.status = payload.status
    if payload.status == CANCELLED:
        rfq.cancel_reason = payload.cancel_reason
    db.add(rfq)

    audit_service.log_event(
        db,
        action=RFQ_STATUS_CHANGED,
        module=PROCUREMENT_MODULE,
        organisation_id=current_user.organisation_id,
        actor_user_id=current_user.id,
        entity_type="rfq",
        entity_id=rfq.id,
        result="success",
        details=f"status: {before_status} -> {payload.status}"
        + (f", reason: {payload.cancel_reason}" if payload.status == CANCELLED else ""),
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    db.refresh(rfq)
    return _build_rfq_out(db, rfq)


@router.post("/{rfq_id}/responses", response_model=RfqOut, status_code=status.HTTP_201_CREATED)
def capture_rfq_response(
    rfq_id: int,
    payload: RfqCaptureResponseRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RfqOut:
    """docs/modules/rfq.md #5/#15 -- `file_ids` must already be uploaded
    via POST /api/files. Only valid once the RFQ has been issued; the
    first captured response moves the RFQ to response_received."""
    rfq_scope.require_permission(db, current_user, rfq_scope.CAPTURE_RESPONSE)
    rfq = _get_rfq_in_org(db, rfq_id, current_user.organisation_id)

    response = rfq_service.capture_response(
        db,
        rfq=rfq,
        response_received_at=payload.response_received_at or datetime.utcnow(),
        note=payload.note,
        created_by_user_id=current_user.id,
    )
    file_service.attach_files(
        db,
        file_ids=payload.file_ids,
        entity_type="rfq_response",
        entity_id=response.id,
        organisation_id=current_user.organisation_id,
    )

    audit_service.log_event(
        db,
        action=RFQ_RESPONSE_CAPTURED,
        module=PROCUREMENT_MODULE,
        organisation_id=current_user.organisation_id,
        actor_user_id=current_user.id,
        entity_type="rfq",
        entity_id=rfq.id,
        result="success",
        details=f"response_id: {response.id}, files: {len(payload.file_ids)}",
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    db.refresh(rfq)
    return _build_rfq_out(db, rfq)


@router.patch("/{rfq_id}/decision", response_model=RfqOut)
def decide_rfq(
    rfq_id: int,
    payload: RfqDecisionRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RfqOut:
    """docs/modules/rfq.md #6 -- only valid once a response has been
    received."""
    rfq_scope.require_permission(db, current_user, rfq_scope.DECIDE)
    rfq = _get_rfq_in_org(db, rfq_id, current_user.organisation_id)

    rfq_service.decide(
        db,
        rfq=rfq,
        decision=payload.decision,
        selected_response_id=payload.selected_response_id,
        decision_note=payload.note,
        decided_by_user_id=current_user.id,
    )

    audit_service.log_event(
        db,
        action=RFQ_DECIDED,
        module=PROCUREMENT_MODULE,
        organisation_id=current_user.organisation_id,
        actor_user_id=current_user.id,
        entity_type="rfq",
        entity_id=rfq.id,
        result="success",
        details=f"decision: {payload.decision}, selected_response_id: {payload.selected_response_id}",
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    db.refresh(rfq)
    return _build_rfq_out(db, rfq)


@router.post("/{rfq_id}/convert-to-po", response_model=RfqOut)
def convert_rfq_to_purchase_order(
    rfq_id: int,
    payload: RfqConvertRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RfqOut:
    """docs/modules/rfq.md #8/#12 -- only valid from `selected`. Supplier
    and each line's material/quantity are carried forward untouched;
    warehouse_id and each line's unit_price are the only new input.
    Never re-submittable once converted -- the status flip is this
    action's own idempotency guard."""
    rfq_scope.require_permission(db, current_user, rfq_scope.CONVERT)
    rfq = _get_rfq_in_org(db, rfq_id, current_user.organisation_id)
    _resolve_active_warehouse(db, payload.warehouse_id, current_user.organisation_id)

    rfq_line_ids = [entry.rfq_line_id for entry in payload.lines]
    if len(set(rfq_line_ids)) != len(rfq_line_ids):
        raise ValidationError("Each RFQ line can only be converted once per request.")
    lines_by_id = {
        line.id: line for line in db.query(RfqLine).filter(RfqLine.rfq_id == rfq.id, RfqLine.id.in_(rfq_line_ids)).all()
    }

    conversion_lines = []
    for entry in payload.lines:
        rfq_line = lines_by_id.get(entry.rfq_line_id)
        if rfq_line is None:
            raise ValidationError("One or more lines do not belong to this RFQ.")
        material = _resolve_active_raw_material(db, rfq_line.raw_material_id, current_user.organisation_id)
        conversion_lines.append(
            rfq_service.RfqConversionLine(raw_material=material, quantity=rfq_line.quantity, unit_price=entry.unit_price)
        )

    purchase_order = rfq_service.convert_to_purchase_order(
        db, rfq=rfq, warehouse_id=payload.warehouse_id, lines=conversion_lines
    )

    audit_service.log_event(
        db,
        action=RFQ_CONVERTED,
        module=PROCUREMENT_MODULE,
        organisation_id=current_user.organisation_id,
        actor_user_id=current_user.id,
        entity_type="rfq",
        entity_id=rfq.id,
        result="success",
        details=f"purchase_order_id: {purchase_order.id}, po_number: {purchase_order.po_number}",
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    db.refresh(rfq)
    return _build_rfq_out(db, rfq)


def _check_rfq_response_file_access(db: Session, user: User, response_id: int) -> bool:
    """Registered against entity_type="rfq_response" -- a response's
    attachment inherits the RFQ's own access rules
    (docs/modules/file_storage.md #5), resolved via the response's owning
    RFQ rather than duplicating an organisation/permission check here."""
    response = db.query(RfqResponse).filter(RfqResponse.id == response_id).first()
    if response is None or response.organisation_id != user.organisation_id:
        return False
    return rfq_scope.can_perform(db, user, rfq_scope.VIEW)


register_entity_access_check("rfq_response", _check_rfq_response_file_access)
