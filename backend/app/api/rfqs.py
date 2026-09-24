from collections import defaultdict
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import exists
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
    RFQ_INVITATION_ADDED,
    RFQ_INVITATION_DECLINED,
    RFQ_INVITATION_REMOVED,
    RFQ_LINE_ADDED,
    RFQ_LINE_REMOVED,
    RFQ_LINE_UPDATED,
    RFQ_RESPONSE_CAPTURED,
    RFQ_STATUS_CHANGED,
    RFQ_UPDATED,
)
from app.models.file import FileRecord
from app.models.raw_material import RawMaterial
from app.models.rfq import (
    CANCELLED,
    CONVERTED,
    DRAFT,
    RFQ_PRIORITIES,
    RFQ_STATUSES,
    Rfq,
    RfqLine,
    RfqResponse,
    RfqResponseLine,
    RfqSupplierInvitation,
)
from app.models.supplier import Supplier
from app.models.team import Team
from app.models.user import User
from app.models.warehouse import Warehouse
from app.schemas.file import FileOut
from app.schemas.pagination import PaginatedResponse
from app.schemas.rfq import (
    RfqCaptureResponseRequest,
    RfqConvertRequest,
    RfqCreateRequest,
    RfqDecisionRequest,
    RfqInvitationCreateRequest,
    RfqInvitationOut,
    RfqLineCreateRequest,
    RfqLineOut,
    RfqLineUpdateRequest,
    RfqOut,
    RfqResponseLineOut,
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
    "priority": Rfq.priority,
    "created_at": Rfq.created_at,
}

_MAX_CODE_ATTEMPTS = 5


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


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


def _get_invitation_in_rfq(db: Session, rfq_id: int, invitation_id: int) -> RfqSupplierInvitation:
    invitation = (
        db.query(RfqSupplierInvitation)
        .filter(RfqSupplierInvitation.id == invitation_id, RfqSupplierInvitation.rfq_id == rfq_id)
        .first()
    )
    if invitation is None:
        raise NotFoundError("Supplier invitation not found.")
    return invitation


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


def _resolve_active_team(db: Session, team_id: int, organisation_id: int) -> Team:
    team = (
        db.query(Team)
        .filter(Team.id == team_id, Team.organisation_id == organisation_id, Team.is_active.is_(True))
        .first()
    )
    if team is None:
        raise ValidationError(
            "team_id must be an active team in your organisation.",
            fields={"team_id": "Not a valid active team in your organisation."},
        )
    return team


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


def _build_rfq_outs(db: Session, rfqs: list[Rfq]) -> list[RfqOut]:
    """Assembles the full nested shape (lines, invitations -> responses ->
    response lines + files) for any number of RFQs in a fixed five
    queries, never one-per-row -- the list endpoint returns the same
    shape as the detail endpoint (docs/modules/rfq.md #6/#18). Every
    child query is keyed by ids already scoped to the caller's
    organisation through the parent `Rfq` rows."""
    if not rfqs:
        return []
    rfq_ids = [rfq.id for rfq in rfqs]

    lines_by_rfq: dict[int, list[RfqLine]] = defaultdict(list)
    for line in db.query(RfqLine).filter(RfqLine.rfq_id.in_(rfq_ids)).order_by(RfqLine.id):
        lines_by_rfq[line.rfq_id].append(line)

    invitations = (
        db.query(RfqSupplierInvitation)
        .filter(RfqSupplierInvitation.rfq_id.in_(rfq_ids))
        .order_by(RfqSupplierInvitation.id)
        .all()
    )
    invitation_ids = [invitation.id for invitation in invitations]

    responses: list[RfqResponse] = []
    if invitation_ids:
        responses = (
            db.query(RfqResponse)
            .filter(RfqResponse.invitation_id.in_(invitation_ids))
            .order_by(RfqResponse.id)
            .all()
        )
    response_ids = [response.id for response in responses]

    response_lines_by_response: dict[int, list[RfqResponseLine]] = defaultdict(list)
    files_by_response: dict[int, list[FileRecord]] = defaultdict(list)
    if response_ids:
        for response_line in (
            db.query(RfqResponseLine)
            .filter(RfqResponseLine.response_id.in_(response_ids))
            .order_by(RfqResponseLine.id)
        ):
            response_lines_by_response[response_line.response_id].append(response_line)
        for record in (
            db.query(FileRecord)
            .filter(
                FileRecord.entity_type == "rfq_response",
                FileRecord.entity_id.in_(response_ids),
                FileRecord.deleted_at.is_(None),
            )
            .order_by(FileRecord.id)
        ):
            files_by_response[record.entity_id].append(record)

    responses_by_invitation: dict[int, list[RfqResponseOut]] = defaultdict(list)
    for response in responses:
        responses_by_invitation[response.invitation_id].append(
            RfqResponseOut(
                id=response.id,
                invitation_id=response.invitation_id,
                response_received_at=response.response_received_at,
                supplier_quotation_number=response.supplier_quotation_number,
                quotation_date=response.quotation_date,
                valid_until=response.valid_until,
                payment_terms=response.payment_terms,
                delivery_terms=response.delivery_terms,
                freight_terms=response.freight_terms,
                note=response.note,
                created_by_user_id=response.created_by_user_id,
                lines=[RfqResponseLineOut.model_validate(row) for row in response_lines_by_response[response.id]],
                files=[FileOut.model_validate(f) for f in files_by_response[response.id]],
            )
        )

    invitations_by_rfq: dict[int, list[RfqInvitationOut]] = defaultdict(list)
    for invitation in invitations:
        invitations_by_rfq[invitation.rfq_id].append(
            RfqInvitationOut(
                id=invitation.id,
                supplier_id=invitation.supplier_id,
                status=invitation.status,
                invited_at=invitation.invited_at,
                responses=responses_by_invitation[invitation.id],
            )
        )

    return [
        RfqOut(
            id=rfq.id,
            organisation_id=rfq.organisation_id,
            rfq_number=rfq.rfq_number,
            status=rfq.status,
            priority=rfq.priority,
            rfq_date=rfq.rfq_date,
            required_delivery_date=rfq.required_delivery_date,
            team_id=rfq.team_id,
            requested_by_user_id=rfq.requested_by_user_id,
            notes=rfq.notes,
            cancel_reason=rfq.cancel_reason,
            decided_by_user_id=rfq.decided_by_user_id,
            decided_at=rfq.decided_at,
            decision_note=rfq.decision_note,
            selected_response_id=rfq.selected_response_id,
            purchase_order_id=rfq.purchase_order_id,
            lines=[RfqLineOut.model_validate(line) for line in lines_by_rfq[rfq.id]],
            invitations=invitations_by_rfq[rfq.id],
        )
        for rfq in rfqs
    ]


def _build_rfq_out(db: Session, rfq: Rfq) -> RfqOut:
    return _build_rfq_outs(db, [rfq])[0]


def _log(db: Session, request: Request, user: User, rfq: Rfq, action: str, details: str) -> None:
    audit_service.log_event(
        db,
        action=action,
        module=PROCUREMENT_MODULE,
        organisation_id=user.organisation_id,
        actor_user_id=user.id,
        entity_type="rfq",
        entity_id=rfq.id,
        result="success",
        details=details,
        ip_address=_client_ip(request),
    )


@router.get("", response_model=PaginatedResponse[RfqOut])
def list_rfqs(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    sort_by: str | None = Query(None),
    sort_direction: Literal["asc", "desc"] = Query("asc"),
    status_filter: str | None = Query(None, alias="status"),
    priority: str | None = Query(None),
    team_id: int | None = Query(None),
    supplier_id: int | None = Query(None),
    q: str | None = Query(None, max_length=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PaginatedResponse[RfqOut]:
    rfq_scope.require_permission(db, current_user, rfq_scope.VIEW)
    if status_filter is not None and status_filter not in RFQ_STATUSES:
        raise ValidationError("Unknown status filter.", fields={"status": "Not a valid RFQ status."})
    if priority is not None and priority not in RFQ_PRIORITIES:
        raise ValidationError("Unknown priority filter.", fields={"priority": "Not a valid RFQ priority."})

    query = db.query(Rfq).filter(Rfq.organisation_id == current_user.organisation_id)
    if status_filter is not None:
        query = query.filter(Rfq.status == status_filter)
    if priority is not None:
        query = query.filter(Rfq.priority == priority)
    if team_id is not None:
        query = query.filter(Rfq.team_id == team_id)
    if supplier_id is not None:
        # "RFQs this supplier was invited to" -- the v2 meaning of the v1
        # header-level supplier filter (docs/modules/rfq.md #4).
        query = query.filter(
            exists().where(
                RfqSupplierInvitation.rfq_id == Rfq.id, RfqSupplierInvitation.supplier_id == supplier_id
            )
        )
    query = apply_keyword_filter(query, q, Rfq.rfq_number)
    query = apply_sort(query, sort_by, sort_direction, _SORT_FIELDS, default=Rfq.id)

    rfqs, pagination = paginate(query, page, page_size)
    return PaginatedResponse(data=_build_rfq_outs(db, rfqs), pagination=pagination)


@router.get("/{rfq_id}", response_model=RfqOut)
def get_rfq(rfq_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> RfqOut:
    """Also the comparison view (docs/modules/rfq.md #6): every invitation
    with its responses and their quoted lines, as stored."""
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
    """Always starts `draft` with no lines and no invitations -- both are
    added afterward (docs/modules/rfq.md #3/#4). `requested_by_user_id`
    is the session user, never client-supplied."""
    rfq_scope.require_permission(db, current_user, rfq_scope.CREATE)
    if payload.team_id is not None:
        _resolve_active_team(db, payload.team_id, current_user.organisation_id)

    rfq: Rfq | None = None
    last_error: IntegrityError | None = None
    for _ in range(_MAX_CODE_ATTEMPTS):
        rfq_number = rfq_service.generate_rfq_number(db, current_user.organisation_id)
        rfq = Rfq(
            organisation_id=current_user.organisation_id,
            rfq_number=rfq_number,
            status=DRAFT,
            priority=payload.priority,
            rfq_date=payload.rfq_date,
            required_delivery_date=payload.required_delivery_date,
            team_id=payload.team_id,
            requested_by_user_id=current_user.id,
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

    _log(db, request, current_user, rfq, RFQ_CREATED, f"rfq_number: {rfq.rfq_number}, priority: {rfq.priority}")
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
    """Draft-only. `requested_by_user_id` has no update path."""
    rfq_scope.require_permission(db, current_user, rfq_scope.CREATE)
    rfq = _get_rfq_in_org(db, rfq_id, current_user.organisation_id)
    _require_draft(rfq)

    updates = payload.model_dump(exclude_unset=True)
    if updates.get("team_id") is not None:
        _resolve_active_team(db, updates["team_id"], current_user.organisation_id)
    rfq_date = updates.get("rfq_date", rfq.rfq_date)
    required_delivery_date = updates.get("required_delivery_date", rfq.required_delivery_date)
    if required_delivery_date is not None and required_delivery_date < rfq_date:
        raise ValidationError(
            "Required delivery date cannot be before the RFQ date.",
            fields={"required_delivery_date": "Cannot be before the RFQ date."},
        )

    before = {field: getattr(rfq, field) for field in updates}
    for field, value in updates.items():
        setattr(rfq, field, value)
    db.add(rfq)
    db.flush()

    changes = audit_service.diff_fields(before, updates)
    if changes:
        _log(db, request, current_user, rfq, RFQ_UPDATED, audit_service.format_changes(changes))
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

    line = RfqLine(rfq_id=rfq.id, raw_material_id=material.id, quantity=payload.quantity, remarks=payload.remarks)
    db.add(line)
    db.flush()

    _log(
        db, request, current_user, rfq, RFQ_LINE_ADDED,
        f"raw_material_id: {line.raw_material_id}, quantity: {line.quantity}",
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

    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(line, field, value)
    db.add(line)
    db.flush()

    _log(
        db, request, current_user, rfq, RFQ_LINE_UPDATED,
        f"line_id: {line.id}, quantity: {line.quantity}, remarks: {line.remarks or '-'}",
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

    _log(db, request, current_user, rfq, RFQ_LINE_REMOVED, f"raw_material_id: {line.raw_material_id}")
    db.delete(line)
    db.commit()


@router.post("/{rfq_id}/invitations", response_model=RfqOut, status_code=status.HTTP_201_CREATED)
def add_rfq_invitation(
    rfq_id: int,
    payload: RfqInvitationCreateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RfqOut:
    """docs/modules/rfq.md #4 -- invitations are part of the draft, so
    they share the "create" permission and the draft-only rule."""
    rfq_scope.require_permission(db, current_user, rfq_scope.CREATE)
    rfq = _get_rfq_in_org(db, rfq_id, current_user.organisation_id)
    _require_draft(rfq)
    supplier = _resolve_active_supplier(db, payload.supplier_id, current_user.organisation_id)

    already_invited = (
        db.query(RfqSupplierInvitation.id)
        .filter(RfqSupplierInvitation.rfq_id == rfq.id, RfqSupplierInvitation.supplier_id == supplier.id)
        .first()
    )
    if already_invited is not None:
        raise ConflictError("This supplier is already invited to this RFQ.")

    invitation = RfqSupplierInvitation(rfq_id=rfq.id, supplier_id=supplier.id, invited_at=datetime.utcnow())
    db.add(invitation)
    try:
        db.flush()
    except IntegrityError as exc:
        # Concurrent duplicate invite lost the race to the unique constraint.
        db.rollback()
        raise ConflictError("This supplier is already invited to this RFQ.") from exc

    _log(db, request, current_user, rfq, RFQ_INVITATION_ADDED, f"supplier_id: {supplier.id}")
    db.commit()
    db.refresh(rfq)
    return _build_rfq_out(db, rfq)


@router.delete("/{rfq_id}/invitations/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_rfq_invitation(
    rfq_id: int,
    invitation_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """Draft-only -- a draft invitation can have no responses yet, so
    removing it never discards captured history."""
    rfq_scope.require_permission(db, current_user, rfq_scope.CREATE)
    rfq = _get_rfq_in_org(db, rfq_id, current_user.organisation_id)
    _require_draft(rfq)
    invitation = _get_invitation_in_rfq(db, rfq.id, invitation_id)

    _log(db, request, current_user, rfq, RFQ_INVITATION_REMOVED, f"supplier_id: {invitation.supplier_id}")
    db.delete(invitation)
    db.commit()


@router.post("/{rfq_id}/invitations/{invitation_id}/decline", response_model=RfqOut)
def decline_rfq_invitation(
    rfq_id: int,
    invitation_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RfqOut:
    """Records a supplier's "no" (or silence) -- a flag only
    (docs/modules/rfq.md #4). Gated like response capture: both record
    what a supplier answered."""
    rfq_scope.require_permission(db, current_user, rfq_scope.CAPTURE_RESPONSE)
    rfq = _get_rfq_in_org(db, rfq_id, current_user.organisation_id)
    invitation = _get_invitation_in_rfq(db, rfq.id, invitation_id)

    rfq_service.decline_invitation(rfq, invitation)
    db.add(invitation)

    _log(db, request, current_user, rfq, RFQ_INVITATION_DECLINED, f"supplier_id: {invitation.supplier_id}")
    db.commit()
    db.refresh(rfq)
    return _build_rfq_out(db, rfq)


@router.patch("/{rfq_id}/status", response_model=RfqOut)
def change_rfq_status(
    rfq_id: int,
    payload: RfqStatusChangeRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RfqOut:
    """Issue or cancel (docs/modules/rfq.md #9/#11) -- gated by the
    "issue" RFQ permission, which covers both lifecycle decisions.
    Issuing requires at least one line and at least one invitation, and
    sends nothing."""
    rfq_scope.require_permission(db, current_user, rfq_scope.ISSUE)
    rfq = _get_rfq_in_org(db, rfq_id, current_user.organisation_id)
    rfq_service.assert_transition_allowed(rfq.status, payload.status)

    if payload.status != CANCELLED:
        rfq_service.assert_can_issue(db, rfq)

    before_status = rfq.status
    rfq.status = payload.status
    if payload.status == CANCELLED:
        rfq.cancel_reason = payload.cancel_reason
    db.add(rfq)

    _log(
        db, request, current_user, rfq, RFQ_STATUS_CHANGED,
        f"status: {before_status} -> {payload.status}"
        + (f", reason: {payload.cancel_reason}" if payload.status == CANCELLED else ""),
    )
    db.commit()
    db.refresh(rfq)
    return _build_rfq_out(db, rfq)


@router.post(
    "/{rfq_id}/invitations/{invitation_id}/responses", response_model=RfqOut, status_code=status.HTTP_201_CREATED
)
def capture_rfq_response(
    rfq_id: int,
    invitation_id: int,
    payload: RfqCaptureResponseRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RfqOut:
    """docs/modules/rfq.md #5/#17 -- structured quoted lines, plus
    optional `file_ids` already uploaded via POST /api/files as
    supporting evidence. Only valid once the RFQ has been issued; the
    first captured response on any invitation moves the RFQ to
    response_received."""
    rfq_scope.require_permission(db, current_user, rfq_scope.CAPTURE_RESPONSE)
    rfq = _get_rfq_in_org(db, rfq_id, current_user.organisation_id)
    invitation = _get_invitation_in_rfq(db, rfq.id, invitation_id)

    response = rfq_service.capture_response(
        db,
        rfq=rfq,
        invitation=invitation,
        response_received_at=payload.response_received_at or datetime.utcnow(),
        supplier_quotation_number=payload.supplier_quotation_number,
        quotation_date=payload.quotation_date,
        valid_until=payload.valid_until,
        payment_terms=payload.payment_terms,
        delivery_terms=payload.delivery_terms,
        freight_terms=payload.freight_terms,
        note=payload.note,
        lines=[
            rfq_service.ResponseLineInput(
                rfq_line_id=line.rfq_line_id,
                unit_price=line.unit_price,
                delivery_days=line.delivery_days,
                remarks=line.remarks,
            )
            for line in payload.lines
        ],
        created_by_user_id=current_user.id,
    )
    if payload.file_ids:
        file_service.attach_files(
            db,
            file_ids=payload.file_ids,
            entity_type="rfq_response",
            entity_id=response.id,
            organisation_id=current_user.organisation_id,
        )

    _log(
        db, request, current_user, rfq, RFQ_RESPONSE_CAPTURED,
        f"response_id: {response.id}, supplier_id: {invitation.supplier_id}, "
        f"lines: {len(payload.lines)}, files: {len(payload.file_ids)}",
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
    """docs/modules/rfq.md #7 -- only valid once a response has been
    received. The selected response may belong to any invited supplier on
    this RFQ; the choice is always a person's, never computed."""
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

    _log(
        db, request, current_user, rfq, RFQ_DECIDED,
        f"decision: {payload.decision}, selected_response_id: {rfq.selected_response_id}",
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
    """docs/modules/rfq.md #8/#14 -- only valid from `selected`. Supplier
    comes from the selected response's invitation; material/quantity
    carry forward from the RFQ lines; unit prices default from the
    selected response and can be overridden per line. `warehouse_id` is
    the only input with no upstream source. Never re-submittable once
    converted -- the status flip is this action's own idempotency
    guard."""
    rfq_scope.require_permission(db, current_user, rfq_scope.CONVERT)
    rfq = _get_rfq_in_org(db, rfq_id, current_user.organisation_id)
    # Transition guard first, so a repeat submission fails as a business
    # rule before any other lookup can mask it with a different error.
    rfq_service.assert_transition_allowed(rfq.status, CONVERTED)
    _resolve_active_warehouse(db, payload.warehouse_id, current_user.organisation_id)
    invitation = rfq_service.get_selected_invitation(db, rfq)
    _resolve_active_supplier(db, invitation.supplier_id, current_user.organisation_id)

    overrides = None
    if payload.lines is not None:
        overrides = {entry.rfq_line_id: entry.unit_price for entry in payload.lines}
    priced_lines = rfq_service.resolve_conversion_prices(db, rfq=rfq, overrides=overrides)

    conversion_lines = [
        rfq_service.RfqConversionLine(
            raw_material=_resolve_active_raw_material(db, rfq_line.raw_material_id, current_user.organisation_id),
            quantity=rfq_line.quantity,
            unit_price=unit_price,
        )
        for rfq_line, unit_price in priced_lines
    ]

    purchase_order = rfq_service.convert_to_purchase_order(
        db,
        rfq=rfq,
        supplier_id=invitation.supplier_id,
        warehouse_id=payload.warehouse_id,
        lines=conversion_lines,
    )

    _log(
        db, request, current_user, rfq, RFQ_CONVERTED,
        f"purchase_order_id: {purchase_order.id}, po_number: {purchase_order.po_number}, "
        f"supplier_id: {invitation.supplier_id}",
    )
    db.commit()
    db.refresh(rfq)
    return _build_rfq_out(db, rfq)


def _check_rfq_response_file_access(db: Session, user: User, response_id: int) -> bool:
    """Registered against entity_type="rfq_response" -- a response's
    attachment inherits the RFQ's own access rules
    (docs/modules/file_storage.md #5)."""
    response = db.query(RfqResponse).filter(RfqResponse.id == response_id).first()
    if response is None or response.organisation_id != user.organisation_id:
        return False
    return rfq_scope.can_perform(db, user, rfq_scope.VIEW)


register_entity_access_check("rfq_response", _check_rfq_response_file_access)
