import io
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import and_, exists, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.entity_access import register_entity_access_check
from app.core.errors import BusinessRuleError, ConflictError, NotFoundError, ValidationError
from app.core.list_query import apply_sort, paginate
from app.core.search import apply_keyword_filter
from app.core.storage import default_storage
from app.models.audit_event import (
    PROCUREMENT_MODULE,
    RFQ_CONVERTED,
    RFQ_CREATED,
    RFQ_DECIDED,
    RFQ_INVITATION_DECLINED,
    RFQ_RESPONSE_CAPTURED,
    RFQ_SEND_FAILED,
    RFQ_SENT,
    RFQ_STATUS_CHANGED,
    RFQ_UPDATED,
)
from app.models.document_template import RFQ_DOCUMENT, DocumentTemplate
from app.models.file import FileRecord
from app.models.raw_material import RawMaterial
from app.models.organisation import Organisation
from app.models.rfq import (
    CANCELLED,
    CONVERTED,
    DRAFT,
    ISSUED,
    RESPONSE_RECEIVED,
    RFQ_PRIORITIES,
    SELECTED,
    RFQ_STATUSES,
    Rfq,
    RfqLine,
    RfqResponse,
    RfqResponseLine,
    RfqSupplierInvitation,
)
from app.models.supplier import Supplier
from app.models.unit import UnitOfMeasure
from app.models.user import User
from app.models.warehouse import Warehouse
from app.schemas.file import FileOut
from app.schemas.pagination import PaginatedResponse
from app.schemas.rfq import (
    RfqCaptureResponseRequest,
    RfqConvertRequest,
    RfqDecisionRequest,
    RfqInvitationOut,
    RfqLineOut,
    RfqOut,
    RfqRaiseNewRequest,
    RfqResponseLineOut,
    RfqResponseOut,
    RfqSaveRequest,
    RfqStatusChangeRequest,
)
from app.services import audit_service, email_service, file_service, rfq_scope, rfq_service
from app.services.rfq_pdf_service import RfqPdfData, RfqPdfLine, generate_rfq_pdf

router = APIRouter(prefix="/api/rfqs", tags=["rfqs"])

_SORT_FIELDS = {
    "rfq_number": Rfq.rfq_number,
    "rfq_date": Rfq.rfq_date,
    "status": Rfq.status,
    "priority": Rfq.priority,
    "created_at": Rfq.created_at,
}

_MAX_CODE_ATTEMPTS = 5

# FileRecord.entity_type values owned by this module.
_RESPONSE_FILE = "rfq_response"
_INVITATION_PDF = "rfq_invitation"
_ACCEPTANCE_FILE = "rfq_acceptance"
_ACCEPTANCE_MIME_TYPES = ("application/pdf", "image/png", "image/jpeg")


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


def _build_rfq_outs(db: Session, rfqs: list[Rfq]) -> list[RfqOut]:
    """Assembles the full nested shape (lines, invitations -> responses ->
    response lines, plus all files) for any number of RFQs in a fixed
    six queries, never one-per-row -- the list endpoint returns the same
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
    if response_ids:
        for response_line in (
            db.query(RfqResponseLine)
            .filter(RfqResponseLine.response_id.in_(response_ids))
            .order_by(RfqResponseLine.id)
        ):
            response_lines_by_response[response_line.response_id].append(response_line)

    # Every file this module owns (response evidence, per-supplier RFQ
    # PDFs, accepted-quotation uploads) in one query.
    files: dict[tuple[str, int], list[FileRecord]] = defaultdict(list)
    file_scopes = [and_(FileRecord.entity_type == _ACCEPTANCE_FILE, FileRecord.entity_id.in_(rfq_ids))]
    if invitation_ids:
        file_scopes.append(and_(FileRecord.entity_type == _INVITATION_PDF, FileRecord.entity_id.in_(invitation_ids)))
    if response_ids:
        file_scopes.append(and_(FileRecord.entity_type == _RESPONSE_FILE, FileRecord.entity_id.in_(response_ids)))
    for record in (
        db.query(FileRecord)
        .filter(FileRecord.organisation_id == rfqs[0].organisation_id, FileRecord.deleted_at.is_(None), or_(*file_scopes))
        .order_by(FileRecord.id)
    ):
        files[(record.entity_type, record.entity_id)].append(record)

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
                files=[FileOut.model_validate(f) for f in files[(_RESPONSE_FILE, response.id)]],
            )
        )

    requester_ids = {rfq.requested_by_user_id for rfq in rfqs if rfq.requested_by_user_id}
    requester_names = (
        dict(db.query(User.id, User.full_name).filter(User.id.in_(requester_ids)).all()) if requester_ids else {}
    )

    invitations_by_rfq: dict[int, list[RfqInvitationOut]] = defaultdict(list)
    for invitation in invitations:
        invitations_by_rfq[invitation.rfq_id].append(
            RfqInvitationOut(
                id=invitation.id,
                supplier_id=invitation.supplier_id,
                status=invitation.status,
                invited_at=invitation.invited_at,
                last_emailed_at=invitation.last_emailed_at,
                # The latest generated PDF is the one to download/email.
                pdf_file=(
                    FileOut.model_validate(files[(_INVITATION_PDF, invitation.id)][-1])
                    if files[(_INVITATION_PDF, invitation.id)]
                    else None
                ),
                responses=responses_by_invitation[invitation.id],
            )
        )

    return [
        RfqOut(
            id=rfq.id,
            organisation_id=rfq.organisation_id,
            rfq_number=rfq.rfq_number,
            status=rfq.status,
            revision_number=rfq.revision_number,
            priority=rfq.priority,
            rfq_date=rfq.rfq_date,
            required_delivery_date=rfq.required_delivery_date,
            requested_by_user_id=rfq.requested_by_user_id,
            requested_by_name=requester_names.get(rfq.requested_by_user_id),
            notes=rfq.notes,
            cancel_reason=rfq.cancel_reason,
            decided_by_user_id=rfq.decided_by_user_id,
            decided_at=rfq.decided_at,
            decision_note=rfq.decision_note,
            selected_response_id=rfq.selected_response_id,
            purchase_order_id=rfq.purchase_order_id,
            lines=[RfqLineOut.model_validate(line) for line in lines_by_rfq[rfq.id]],
            invitations=invitations_by_rfq[rfq.id],
            acceptance_files=[FileOut.model_validate(f) for f in files[(_ACCEPTANCE_FILE, rfq.id)]],
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


@router.get("/next-number")
def next_rfq_number(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """The number the next new RFQ will get, shown in the New RFQ form.
    Not reserved -- the number is assigned when the RFQ is saved."""
    rfq_scope.require_permission(db, current_user, rfq_scope.CREATE)
    return {"rfq_number": rfq_service.generate_rfq_number(db, current_user.organisation_id)}


@router.get("/{rfq_id}", response_model=RfqOut)
def get_rfq(rfq_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> RfqOut:
    """Also the comparison view (docs/modules/rfq.md #6): every invitation
    with its responses and their quoted lines, as stored."""
    rfq_scope.require_permission(db, current_user, rfq_scope.VIEW)
    rfq = _get_rfq_in_org(db, rfq_id, current_user.organisation_id)
    return _build_rfq_out(db, rfq)


def _validate_form(db: Session, payload: RfqSaveRequest, organisation_id: int) -> tuple[list[Supplier], dict]:
    """Every rule of the RFQ form (docs/modules/rfq.md #2-#4), checked
    before anything is written: active registered
    suppliers, active materials, and a unit that converts to each
    material's own unit. Returns the resolved rows."""
    today = date.today()
    if payload.required_delivery_date < today:
        raise ValidationError(
            "Required By date cannot be in the past.", fields={"required_delivery_date": "Cannot be in the past."}
        )

    suppliers = (
        db.query(Supplier)
        .filter(Supplier.id.in_(payload.supplier_ids), Supplier.organisation_id == organisation_id, Supplier.is_active.is_(True))
        .all()
    )
    if len(suppliers) != len(payload.supplier_ids):
        raise ValidationError(
            "Every supplier must be an active registered supplier in your organisation.",
            fields={"supplier_ids": "One or more suppliers are not valid."},
        )

    material_ids = {line.raw_material_id for line in payload.lines}
    materials = {
        m.id: m
        for m in db.query(RawMaterial).filter(
            RawMaterial.id.in_(material_ids), RawMaterial.organisation_id == organisation_id, RawMaterial.is_active.is_(True)
        )
    }
    unit_ids = {line.unit_of_measure_id for line in payload.lines} | {m.unit_of_measure_id for m in materials.values()} | {
        m.alternate_conversion_unit_of_measure_id for m in materials.values() if m.alternate_conversion_unit_of_measure_id
    }
    units = {u.id: u for u in db.query(UnitOfMeasure).filter(UnitOfMeasure.id.in_(unit_ids), UnitOfMeasure.organisation_id == organisation_id)}

    for index, line in enumerate(payload.lines, start=1):
        material = materials.get(line.raw_material_id)
        if material is None:
            raise ValidationError(
                f"Item {index}: not an active product/material in your organisation.",
                fields={"lines": f"Item {index}: invalid product/material."},
            )
        unit = units.get(line.unit_of_measure_id)
        if unit is None or not unit.is_active:
            raise ValidationError(
                f"Item {index}: not an active unit in your organisation.", fields={"lines": f"Item {index}: invalid unit."}
            )
        material_unit = units[material.unit_of_measure_id]
        alternate = units.get(material.alternate_conversion_unit_of_measure_id) if material.alternate_conversion_unit_of_measure_id else None
        if rfq_service.line_unit_ratio(unit, material, alternate, material_unit) is None:
            raise ValidationError(
                f"Item {index}: {material.name} cannot be requested in {unit.code} -- "
                f"there is no conversion to its unit {material_unit.code}.",
                fields={"lines": f"Item {index}: unit has no conversion to {material_unit.code}."},
            )
        if line.required_by_date is not None and line.required_by_date < today:
            raise ValidationError(
                f"Item {index}: Required By date cannot be in the past.", fields={"lines": f"Item {index}: date in the past."}
            )
    return suppliers, {"materials": materials, "units": units}


def _write_form(db: Session, rfq: Rfq, payload: RfqSaveRequest) -> None:
    """Applies the form to `rfq`: header fields, lines replaced wholesale
    (only ever called while no quote references them), invitations
    reconciled by supplier so a kept supplier keeps its invitation and
    PDF history."""
    rfq.required_delivery_date = payload.required_delivery_date
    rfq.priority = payload.priority
    db.add(rfq)

    db.query(RfqLine).filter(RfqLine.rfq_id == rfq.id).delete(synchronize_session=False)
    db.add_all(
        RfqLine(
            rfq_id=rfq.id,
            raw_material_id=line.raw_material_id,
            quantity=line.quantity,
            unit_of_measure_id=line.unit_of_measure_id,
            required_by_date=line.required_by_date,
            remarks=line.remarks,
        )
        for line in payload.lines
    )

    existing = {
        invitation.supplier_id: invitation
        for invitation in db.query(RfqSupplierInvitation).filter(RfqSupplierInvitation.rfq_id == rfq.id)
    }
    wanted = set(payload.supplier_ids)
    for supplier_id, invitation in existing.items():
        if supplier_id not in wanted:
            db.delete(invitation)
    now = datetime.utcnow()
    db.add_all(
        RfqSupplierInvitation(rfq_id=rfq.id, supplier_id=supplier_id, invited_at=now)
        for supplier_id in payload.supplier_ids
        if supplier_id not in existing
    )
    db.flush()


def _render_pdfs(db: Session, rfq: Rfq, resolved: dict) -> list[tuple[RfqSupplierInvitation, bytes]]:
    """One letterhead PDF per invited supplier for the current revision
    (docs/modules/rfq.md #11). Rendered in memory, before anything is
    committed."""
    organisation = db.query(Organisation).filter(Organisation.id == rfq.organisation_id).one()
    template = (
        db.query(DocumentTemplate)
        .filter(DocumentTemplate.organisation_id == rfq.organisation_id, DocumentTemplate.document_type == RFQ_DOCUMENT)
        .first()
    )
    letterhead: bytes | None = None
    if template is not None and template.letterhead_file_id is not None:
        record = (
            db.query(FileRecord)
            .filter(
                FileRecord.id == template.letterhead_file_id,
                FileRecord.organisation_id == rfq.organisation_id,
                FileRecord.deleted_at.is_(None),
            )
            .first()
        )
        if record is not None:
            letterhead = b"".join(default_storage.download(record.storage_key))

    requested_by = db.query(User.full_name).filter(User.id == rfq.requested_by_user_id).scalar()
    materials, units = resolved["materials"], resolved["units"]
    lines = db.query(RfqLine).filter(RfqLine.rfq_id == rfq.id).order_by(RfqLine.id).all()
    pdf_lines = [
        RfqPdfLine(
            material_name=materials[line.raw_material_id].name,
            quantity=line.quantity,
            unit_code=units[line.unit_of_measure_id].code,
            remarks=line.remarks,
        )
        for line in lines
    ]
    suppliers = {s.id: s for s in resolved["suppliers"]}
    invitations = (
        db.query(RfqSupplierInvitation).filter(RfqSupplierInvitation.rfq_id == rfq.id).order_by(RfqSupplierInvitation.id).all()
    )

    rendered = []
    for invitation in invitations:
        supplier = suppliers[invitation.supplier_id]
        rendered.append(
            (
                invitation,
                generate_rfq_pdf(
                    RfqPdfData(
                        organisation_name=organisation.name,
                        organisation_address=organisation.address,
                        organisation_phone=organisation.contact_phone,
                        organisation_email=organisation.contact_email,
                        rfq_number=rfq.rfq_number,
                        revision_number=rfq.revision_number,
                        rfq_date=rfq.rfq_date,
                        required_delivery_date=rfq.required_delivery_date,
                        requested_by=requested_by,
                        priority=rfq.priority,
                        notes=rfq.notes,
                        supplier_name=supplier.name,
                        supplier_address=supplier.address,
                        supplier_contact_person=supplier.contact_person,
                        supplier_email=supplier.email,
                        lines=pdf_lines,
                        letterhead_image=letterhead,
                        margin_top_mm=template.margin_top_mm if template else 40,
                        margin_bottom_mm=template.margin_bottom_mm if template else 25,
                        intro_text=template.intro_text if template else None,
                        terms_text=template.terms_text if template else None,
                        signature_text=template.signature_text if template else None,
                    )
                ),
            )
        )
    return rendered


def _save(db: Session, request: Request, user: User, rfq: Rfq, payload: RfqSaveRequest, resolved: dict, created: bool) -> RfqOut:
    """Shared tail of create/edit: write the form, and on submit move to
    the next revision (`draft -> issued`, or a new revision of an issued
    RFQ) and store one PDF per supplier. `upload_file` commits, so the
    audit event is logged first and lands in the same commit as the RFQ
    changes."""
    _write_form(db, rfq, payload)

    rendered: list[tuple[RfqSupplierInvitation, bytes]] = []
    if payload.submit:
        if rfq.status == DRAFT:
            rfq_service.assert_transition_allowed(rfq.status, ISSUED)
            rfq.status = ISSUED
        rfq.revision_number += 1
        db.add(rfq)
        db.flush()
        rendered = _render_pdfs(db, rfq, resolved)

    action = RFQ_CREATED if created else RFQ_UPDATED
    details = f"rfq_number: {rfq.rfq_number}, items: {len(payload.lines)}, suppliers: {len(payload.supplier_ids)}"
    if payload.submit:
        details += f", submitted revision {rfq.revision_number}"
    _log(db, request, user, rfq, action, details)

    if not rendered:
        db.commit()
    for invitation, pdf_bytes in rendered:
        file_service.upload_file(
            db,
            organisation_id=user.organisation_id,
            uploaded_by_user_id=user.id,
            filename=f"RFQ-{rfq.rfq_number}-Rev{rfq.revision_number}-{invitation.supplier_id}.pdf",
            stream=io.BytesIO(pdf_bytes),
            entity_type=_INVITATION_PDF,
            entity_id=invitation.id,
        )
    db.refresh(rfq)
    return _build_rfq_out(db, rfq)


@router.post("", response_model=RfqOut, status_code=status.HTTP_201_CREATED)
def create_rfq(
    payload: RfqSaveRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RfqOut:
    """The New RFQ modal (docs/modules/rfq.md #2-#4): saves a draft, or
    with `submit` issues revision 1 and generates the supplier PDFs."""
    rfq_scope.require_permission(db, current_user, rfq_scope.CREATE)
    if payload.submit:
        rfq_scope.require_permission(db, current_user, rfq_scope.ISSUE)
    suppliers, resolved = _validate_form(db, payload, current_user.organisation_id)
    resolved["suppliers"] = suppliers

    rfq: Rfq | None = None
    last_error: IntegrityError | None = None
    for _ in range(_MAX_CODE_ATTEMPTS):
        rfq = Rfq(
            organisation_id=current_user.organisation_id,
            rfq_number=rfq_service.generate_rfq_number(db, current_user.organisation_id),
            status=DRAFT,
            rfq_date=date.today(),
            required_delivery_date=payload.required_delivery_date,
            requested_by_user_id=current_user.id,
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

    return _save(db, request, current_user, rfq, payload, resolved, created=True)


@router.put("/{rfq_id}", response_model=RfqOut)
def update_rfq(
    rfq_id: int,
    payload: RfqSaveRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RfqOut:
    """Edit the RFQ in the same modal (docs/modules/rfq.md #9). A draft
    can be saved or submitted. An issued RFQ can be revised -- always
    re-submitted as the next revision with fresh PDFs -- only until the
    first quote is captured, since quotes are against its lines."""
    rfq_scope.require_permission(db, current_user, rfq_scope.CREATE)
    rfq = _get_rfq_in_org(db, rfq_id, current_user.organisation_id)
    if rfq.status == ISSUED:
        if not payload.submit:
            raise BusinessRuleError("An issued RFQ can only be changed by submitting a new revision.")
    elif rfq.status != DRAFT:
        raise BusinessRuleError("This RFQ can no longer be changed.")
    if payload.submit:
        rfq_scope.require_permission(db, current_user, rfq_scope.ISSUE)
    has_quote = (
        db.query(RfqResponse.id)
        .join(RfqSupplierInvitation, RfqSupplierInvitation.id == RfqResponse.invitation_id)
        .filter(RfqSupplierInvitation.rfq_id == rfq.id)
        .first()
        is not None
    )
    if has_quote:
        raise BusinessRuleError("This RFQ can no longer be changed -- a supplier quote has already been captured.")

    suppliers, resolved = _validate_form(db, payload, current_user.organisation_id)
    resolved["suppliers"] = suppliers
    return _save(db, request, current_user, rfq, payload, resolved, created=False)


@router.post("/{rfq_id}/invitations/{invitation_id}/send", response_model=RfqOut)
def send_rfq_to_supplier(
    rfq_id: int,
    invitation_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RfqOut:
    """Emails this supplier's current-revision PDF via the organisation's
    mailbox (app/services/email_service.py, same flow as the PO send). A
    failed send is audited and re-raised; nothing is marked sent."""
    rfq_scope.require_permission(db, current_user, rfq_scope.ISSUE)
    rfq = _get_rfq_in_org(db, rfq_id, current_user.organisation_id)
    invitation = _get_invitation_in_rfq(db, rfq.id, invitation_id)
    if rfq.status not in (ISSUED, RESPONSE_RECEIVED):
        raise BusinessRuleError("Only a submitted RFQ that is still open can be emailed.")

    pdf_file = (
        db.query(FileRecord)
        .filter(
            FileRecord.entity_type == _INVITATION_PDF,
            FileRecord.entity_id == invitation.id,
            FileRecord.organisation_id == current_user.organisation_id,
            FileRecord.deleted_at.is_(None),
        )
        .order_by(FileRecord.id.desc())
        .first()
    )
    if pdf_file is None:
        raise BusinessRuleError("No RFQ document has been generated for this supplier.")
    supplier = db.query(Supplier).filter(Supplier.id == invitation.supplier_id).one()
    if not supplier.email:
        raise ValidationError("This supplier has no email address on file.", fields={"supplier_id": "Missing email address."})

    pdf_bytes = b"".join(default_storage.download(pdf_file.storage_key))
    subject = f"Request for Quotation {rfq.rfq_number} (Rev {rfq.revision_number})"
    body = (
        f"Dear {supplier.name},\n\nPlease find attached our Request for Quotation {rfq.rfq_number} "
        f"(Revision {rfq.revision_number}). Kindly send us your best quotation.\n\nRegards."
    )
    try:
        email_service.send_email(
            db, current_user.organisation_id, supplier.email, subject, body, pdf_bytes, pdf_file.original_filename
        )
    except BusinessRuleError as exc:
        audit_service.log_event(
            db,
            action=RFQ_SEND_FAILED,
            module=PROCUREMENT_MODULE,
            organisation_id=current_user.organisation_id,
            actor_user_id=current_user.id,
            entity_type="rfq",
            entity_id=rfq.id,
            result="failure",
            details=str(exc),
            ip_address=_client_ip(request),
        )
        db.commit()
        raise

    invitation.last_emailed_at = datetime.utcnow()
    db.add(invitation)
    _log(db, request, current_user, rfq, RFQ_SENT, f"revision: {rfq.revision_number}, to: {supplier.email}")
    db.commit()
    db.refresh(rfq)
    return _build_rfq_out(db, rfq)


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
    """Cancel only (docs/modules/rfq.md #9) -- requires a reason.
    Submitting is done through the RFQ form itself."""
    rfq_scope.require_permission(db, current_user, rfq_scope.ISSUE)
    rfq = _get_rfq_in_org(db, rfq_id, current_user.organisation_id)
    rfq_service.assert_transition_allowed(rfq.status, payload.status)

    before_status = rfq.status
    rfq.status = payload.status
    rfq.cancel_reason = payload.cancel_reason
    db.add(rfq)

    _log(
        db, request, current_user, rfq, RFQ_STATUS_CHANGED,
        f"status: {before_status} -> {payload.status}, reason: {payload.cancel_reason}",
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
    received. Accepting (`selected`) requires the accepted quotation as
    PDF/image (`file_ids`, uploaded via POST /api/files), attached in the
    same transaction -- no PO can be created without it. Rejecting ends
    the RFQ."""
    rfq_scope.require_permission(db, current_user, rfq_scope.DECIDE)
    rfq = _get_rfq_in_org(db, rfq_id, current_user.organisation_id)

    if payload.decision == SELECTED:
        uploads = (
            db.query(FileRecord)
            .filter(
                FileRecord.id.in_(payload.file_ids),
                FileRecord.organisation_id == current_user.organisation_id,
                FileRecord.deleted_at.is_(None),
            )
            .all()
        )
        if len(uploads) != len(set(payload.file_ids)) or any(f.mime_type not in _ACCEPTANCE_MIME_TYPES for f in uploads):
            raise ValidationError(
                "The supplier's document must be a PDF or image (PNG/JPEG) uploaded to your organisation.",
                fields={"file_ids": "Upload a PDF, PNG or JPEG file."},
            )

    rfq_service.decide(
        db,
        rfq=rfq,
        decision=payload.decision,
        selected_response_id=payload.selected_response_id,
        decision_note=payload.note,
        decided_by_user_id=current_user.id,
    )
    if payload.decision == SELECTED:
        file_service.attach_files(
            db,
            file_ids=payload.file_ids,
            entity_type=_ACCEPTANCE_FILE,
            entity_id=rfq.id,
            organisation_id=current_user.organisation_id,
        )

    _log(
        db, request, current_user, rfq, RFQ_DECIDED,
        f"decision: {payload.decision}, selected_response_id: {rfq.selected_response_id}, "
        f"files: {len(payload.file_ids) if payload.decision == SELECTED else 0}",
    )
    db.commit()
    db.refresh(rfq)
    return _build_rfq_out(db, rfq)


@router.post("/{rfq_id}/raise-new", response_model=RfqOut, status_code=status.HTTP_201_CREATED)
def raise_new_rfq(
    rfq_id: int,
    payload: RfqRaiseNewRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RfqOut:
    """The agreed quantity differs from the request, so this RFQ can't be
    approved (docs/modules/rfq.md #7): it is cancelled, naming its
    replacement, and a new draft RFQ is raised -- same
    priority, suppliers and items, at the agreed quantities -- for the
    user to check and submit. One transaction. Returns the new draft."""
    rfq_scope.require_permission(db, current_user, rfq_scope.CREATE)
    rfq_scope.require_permission(db, current_user, rfq_scope.ISSUE)
    rfq = _get_rfq_in_org(db, rfq_id, current_user.organisation_id)
    if rfq.status != RESPONSE_RECEIVED:
        raise BusinessRuleError("Another RFQ can only be raised from an RFQ awaiting approval.")

    lines = db.query(RfqLine).filter(RfqLine.rfq_id == rfq.id).order_by(RfqLine.id).all()
    lines_by_id = {line.id: line for line in lines}
    agreed = {entry.rfq_line_id: entry.quantity for entry in payload.lines}
    if len(agreed) != len(payload.lines) or any(line_id not in lines_by_id for line_id in agreed):
        raise ValidationError("One or more lines do not belong to this RFQ.", fields={"lines": "Invalid line."})
    if all(agreed[line_id] == lines_by_id[line_id].quantity for line_id in agreed):
        raise BusinessRuleError("The agreed quantities match the request -- approve this RFQ instead.")

    new_rfq: Rfq | None = None
    last_error: IntegrityError | None = None
    for _ in range(_MAX_CODE_ATTEMPTS):
        new_rfq = Rfq(
            organisation_id=rfq.organisation_id,
            rfq_number=rfq_service.generate_rfq_number(db, rfq.organisation_id),
            status=DRAFT,
            rfq_date=date.today(),
            required_delivery_date=rfq.required_delivery_date,
            priority=rfq.priority,
            notes=rfq.notes,
            requested_by_user_id=current_user.id,
        )
        db.add(new_rfq)
        try:
            db.flush()
            last_error = None
            break
        except IntegrityError as exc:
            db.rollback()
            last_error = exc
    if last_error is not None or new_rfq is None:
        raise ConflictError("Could not generate a unique RFQ number. Please try again.") from last_error

    db.add_all(
        RfqLine(
            rfq_id=new_rfq.id,
            raw_material_id=line.raw_material_id,
            quantity=agreed.get(line.id, line.quantity),
            unit_of_measure_id=line.unit_of_measure_id,
            required_by_date=line.required_by_date,
            remarks=line.remarks,
        )
        for line in lines
    )
    now = datetime.utcnow()
    db.add_all(
        RfqSupplierInvitation(rfq_id=new_rfq.id, supplier_id=invitation.supplier_id, invited_at=now)
        for invitation in db.query(RfqSupplierInvitation)
        .filter(RfqSupplierInvitation.rfq_id == rfq.id)
        .order_by(RfqSupplierInvitation.id)
    )

    rfq_service.assert_transition_allowed(rfq.status, CANCELLED)
    rfq.status = CANCELLED
    rfq.cancel_reason = f"Agreed quantity differs from the request -- replaced by RFQ {new_rfq.rfq_number}."
    db.add(rfq)

    _log(db, request, current_user, rfq, RFQ_STATUS_CHANGED, f"status: response_received -> cancelled, reason: {rfq.cancel_reason}")
    _log(db, request, current_user, new_rfq, RFQ_CREATED, f"rfq_number: {new_rfq.rfq_number}, raised from RFQ {rfq.rfq_number}")
    db.commit()
    db.refresh(new_rfq)
    return _build_rfq_out(db, new_rfq)


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
    has_acceptance = (
        db.query(FileRecord.id)
        .filter(
            FileRecord.entity_type == _ACCEPTANCE_FILE,
            FileRecord.entity_id == rfq.id,
            FileRecord.organisation_id == current_user.organisation_id,
            FileRecord.deleted_at.is_(None),
        )
        .first()
        is not None
    )
    if not has_acceptance:
        raise BusinessRuleError("Upload the supplier's document before creating the purchase order.")
    if payload.expected_delivery_date < date.today():
        raise ValidationError(
            "Expected delivery date cannot be in the past.",
            fields={"expected_delivery_date": "Cannot be in the past."},
        )
    _resolve_active_warehouse(db, payload.warehouse_id, current_user.organisation_id)
    invitation = rfq_service.get_selected_invitation(db, rfq)
    _resolve_active_supplier(db, invitation.supplier_id, current_user.organisation_id)

    overrides = None
    if payload.lines is not None:
        overrides = {entry.rfq_line_id: entry.unit_price for entry in payload.lines}
    priced_lines = rfq_service.resolve_conversion_prices(db, rfq=rfq, overrides=overrides)

    # PO lines keep the RFQ line's unit, quantity and price exactly as
    # agreed; the unit's ratio to the material's own unit is stored on the
    # line so receiving posts stock correctly.
    conversion_lines = []
    for rfq_line, unit_price in priced_lines:
        material = _resolve_active_raw_material(db, rfq_line.raw_material_id, current_user.organisation_id)
        ratio = Decimal(1)
        if rfq_line.unit_of_measure_id != material.unit_of_measure_id:
            unit_ids = [rfq_line.unit_of_measure_id, material.unit_of_measure_id]
            if material.alternate_conversion_unit_of_measure_id:
                unit_ids.append(material.alternate_conversion_unit_of_measure_id)
            units = {u.id: u for u in db.query(UnitOfMeasure).filter(UnitOfMeasure.id.in_(unit_ids))}
            ratio = rfq_service.line_unit_ratio(
                units[rfq_line.unit_of_measure_id],
                material,
                units.get(material.alternate_conversion_unit_of_measure_id),
                units[material.unit_of_measure_id],
            )
            if ratio is None:
                raise BusinessRuleError(
                    f"{material.name}: the requested unit no longer converts to its unit. Update the unit setup first."
                )
        conversion_lines.append(
            rfq_service.RfqConversionLine(
                raw_material=material,
                quantity=rfq_line.quantity,
                unit_price=unit_price,
                unit_of_measure_id=rfq_line.unit_of_measure_id,
                conversion_factor=ratio,
                required_by_date=rfq_line.required_by_date,
                remarks=rfq_line.remarks,
            )
        )

    purchase_order = rfq_service.convert_to_purchase_order(
        db,
        rfq=rfq,
        supplier_id=invitation.supplier_id,
        warehouse_id=payload.warehouse_id,
        expected_delivery_date=payload.expected_delivery_date,
        payment_terms=payload.payment_terms,
        supplier_reference=payload.supplier_reference,
        notes=payload.notes,
        lines=conversion_lines,
        rfq_response_id=rfq.selected_response_id,
        created_by_user_id=current_user.id,
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


def _check_rfq_invitation_file_access(db: Session, user: User, invitation_id: int) -> bool:
    """A supplier's RFQ PDF inherits the RFQ's access rules."""
    organisation_id = (
        db.query(Rfq.organisation_id)
        .join(RfqSupplierInvitation, RfqSupplierInvitation.rfq_id == Rfq.id)
        .filter(RfqSupplierInvitation.id == invitation_id)
        .scalar()
    )
    return organisation_id == user.organisation_id and rfq_scope.can_perform(db, user, rfq_scope.VIEW)


def _check_rfq_acceptance_file_access(db: Session, user: User, rfq_id: int) -> bool:
    """The accepted-quotation upload inherits the RFQ's access rules."""
    organisation_id = db.query(Rfq.organisation_id).filter(Rfq.id == rfq_id).scalar()
    return organisation_id == user.organisation_id and rfq_scope.can_perform(db, user, rfq_scope.VIEW)


register_entity_access_check(_RESPONSE_FILE, _check_rfq_response_file_access)
register_entity_access_check(_INVITATION_PDF, _check_rfq_invitation_file_access)
register_entity_access_check(_ACCEPTANCE_FILE, _check_rfq_acceptance_file_access)
