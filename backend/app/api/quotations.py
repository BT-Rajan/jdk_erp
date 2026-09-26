"""Quotation data foundation (Sales S4): create a draft quotation and read
it back. Every path is scoped through the quotation's customer
(app/services/customer_scope.py, Sales S2) -- a quotation whose customer
is outside the caller's scope is a 404, exactly like the customer
itself. There is no quotation-specific ownership or permission key."""

import json

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import or_
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_current_user, require_admin
from app.core.database import get_db
from app.core.errors import AccessDeniedError, NotFoundError, ValidationError
from app.core.list_query import paginate
from app.core.timezone import now_jdk
from app.models.audit_event import (
    FEASIBILITY_DECIDED,
    FEASIBILITY_RECORDED,
    QUOTATION_CREATED,
    QUOTATION_PRICE_DECIDED,
    QUOTATION_READINESS_ASSESSED,
    QUOTATION_UPDATED,
    SALES_MODULE,
)
from app.models.customer import Customer
from app.models.feasibility_check import FeasibilityCheck
from app.models.quotation import DRAFT, Quotation
from app.models.user import User
from app.schemas.pagination import PaginatedResponse
from app.schemas.quotation import (
    FeasibilityCalculationOut,
    FeasibilityCheckLineOut,
    FeasibilityCheckOut,
    FeasibilityDecisionRequest,
    QuotationCreateRequest,
    QuotationListRowOut,
    QuotationLineOut,
    QuotationOut,
    QuotationReadinessOut,
    QuotationUpdateRequest,
    SameDayGateOut,
)
from app.services import (
    audit_service,
    customer_scope,
    feasibility_record_service,
    feasibility_service,
    quotation_readiness_service,
    quotation_service,
    same_day_fg_service,
)

router = APIRouter(prefix="/api/quotations", tags=["quotations"])


def _scoped_query(db: Session, user: User):
    query = (
        db.query(Quotation)
        .options(selectinload(Quotation.lines))
        .filter(Quotation.organisation_id == user.organisation_id)
    )
    return customer_scope.scope_by_customer(db, user, query, Quotation.customer_id)


def _get_visible_quotation(db: Session, quotation_id: int, user: User) -> Quotation:
    quotation = _scoped_query(db, user).filter(Quotation.id == quotation_id).first()
    if quotation is None:
        raise NotFoundError("Quotation not found.")
    return quotation


def _is_owner(quotation: Quotation, user: User) -> bool:
    """Editing authority (S11.2 decision): only the salesman who owns the
    quotation's customer -- Customer.assigned_to_user_id, the S2
    ownership pointer -- may edit it. Seeing it is not enough."""
    return quotation.customer is not None and quotation.customer.assigned_to_user_id == user.id


def _list_row(db: Session, quotation: Quotation, user: User) -> QuotationListRowOut:
    readiness = quotation_readiness_service.assess(db, quotation)
    row = QuotationListRowOut.model_validate(quotation)
    row.delivery_window = readiness.delivery_window
    row.readiness_status = readiness.status
    row.can_edit = quotation.status == DRAFT and _is_owner(quotation, user)
    return row


@router.get("", response_model=PaginatedResponse[QuotationListRowOut])
def list_quotations(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    q: str | None = Query(None, max_length=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PaginatedResponse[QuotationListRowOut]:
    """Scoped server-side through the customer (S2); each row carries the
    server's current delivery window and readiness (read-only, not
    audited -- POST .../readiness is the recorded assessment). `q`
    matches the quotation number or customer name."""
    query = _scoped_query(db, current_user)
    if q:
        query = query.join(Customer, Customer.id == Quotation.customer_id).filter(
            or_(Quotation.quotation_number.ilike(f"%{q}%"), Customer.name.ilike(f"%{q}%"))
        )
    query = query.order_by(Quotation.id.desc())
    quotations, pagination = paginate(query, page, page_size)
    return PaginatedResponse(data=[_list_row(db, q_, current_user) for q_ in quotations], pagination=pagination)


@router.get("/{quotation_id}", response_model=QuotationListRowOut)
def get_quotation(
    quotation_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> QuotationListRowOut:
    return _list_row(db, _get_visible_quotation(db, quotation_id, current_user), current_user)


@router.patch("/{quotation_id}", response_model=QuotationListRowOut)
def update_quotation(
    quotation_id: int,
    payload: QuotationUpdateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> QuotationListRowOut:
    """Controlled edit of a draft quotation (Sales S10). A quotation outside
    the caller's scope is a 404; one the caller can see but doesn't own
    (S11.2: only the salesman owning its customer may edit) is a 403 --
    heads, Admins and other viewers included. A new customer must be in
    scope, owned by the caller and active. Lines are re-validated and
    re-priced on the server. Changing customer, date or lines makes
    earlier feasibility stale. Audited."""
    quotation = _get_visible_quotation(db, quotation_id, current_user)
    if not _is_owner(quotation, current_user):
        raise AccessDeniedError("Only the salesman who owns this customer can edit the quotation.")
    updates = payload.model_dump(exclude_unset=True)
    customer_id = None
    if updates.get("customer_id") is not None:
        customer = customer_scope.get_accessible_customer(db, current_user, updates["customer_id"])
        if customer.assigned_to_user_id != current_user.id:
            raise AccessDeniedError("A quotation can only be moved to a customer you own.")
        if not customer.is_active:
            raise ValidationError(
                "This customer is inactive and cannot be quoted.", fields={"customer_id": "Customer is inactive."}
            )
        customer_id = customer.id
    kwargs = {}
    if "requested_delivery_date" in updates:
        kwargs["requested_delivery_date"] = updates["requested_delivery_date"]
    lines = None
    if payload.lines is not None:
        lines = [
            quotation_service.LineInput(
                product_id=line.product_id,
                quantity=line.quantity,
                unit_of_measure_id=line.unit_of_measure_id,
                unit_price=line.unit_price,
            )
            for line in payload.lines
        ]
    changed = quotation_service.update_quotation(
        db, quotation, today=now_jdk().date(), customer_id=customer_id, lines=lines, **kwargs
    )
    if changed:
        audit_service.log_event(
            db,
            action=QUOTATION_UPDATED,
            module=SALES_MODULE,
            organisation_id=current_user.organisation_id,
            actor_user_id=current_user.id,
            entity_type="quotation",
            entity_id=quotation.id,
            result="success",
            details=(
                f"number: {quotation.quotation_number}, changed: {', '.join(changed)}, "
                f"customer_id: {quotation.customer_id}, requested_delivery_date: {quotation.requested_delivery_date}, "
                f"total: {quotation.total_amount} {quotation.currency}"
            ),
            ip_address=request.client.host if request.client else None,
        )
    db.commit()
    db.expire_all()
    return _list_row(db, _get_visible_quotation(db, quotation_id, current_user), current_user)


@router.put("/{quotation_id}/price-decision", response_model=QuotationListRowOut)
def decide_price(
    quotation_id: int,
    payload: FeasibilityDecisionRequest,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> QuotationListRowOut:
    """Admin/Super Admin only: approve or reject the quotation's prices
    while any line is outside its product's permitted range (or the
    product has no full range). A reason is required and every decision
    is audited. Replacing the lines clears it. Refused when no line needs
    price approval."""
    quotation = _get_visible_quotation(db, quotation_id, admin)
    previous = quotation_service.decide_price(db, quotation, payload.decision, payload.reason, admin.id)
    flagged = [str(line.line_number) for line in quotation.lines if line.price_approval_required]
    audit_service.log_event(
        db,
        action=QUOTATION_PRICE_DECIDED,
        module=SALES_MODULE,
        organisation_id=admin.organisation_id,
        actor_user_id=admin.id,
        entity_type="quotation",
        entity_id=quotation.id,
        result="success",
        details=(
            f"number: {quotation.quotation_number}, decision: {previous} -> {payload.decision}; "
            f"reason: {payload.reason}; lines needing approval: {', '.join(flagged)}"
        ),
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    db.expire_all()
    return _list_row(db, _get_visible_quotation(db, quotation_id, admin), admin)


@router.get("/{quotation_id}/lines", response_model=list[QuotationLineOut])
def get_quotation_lines(
    quotation_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    return _get_visible_quotation(db, quotation_id, current_user).lines


@router.post("", response_model=QuotationOut, status_code=status.HTTP_201_CREATED)
def create_quotation(
    payload: QuotationCreateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Quotation:
    """The customer must be in the caller's scope (404 otherwise, never
    confirming it exists) and active. Number, date (Kuwait), currency,
    status and every amount are set server-side."""
    customer = customer_scope.get_accessible_customer(db, current_user, payload.customer_id)
    if not customer.is_active:
        raise ValidationError(
            "This customer is inactive and cannot be quoted.", fields={"customer_id": "Customer is inactive."}
        )

    quotation = quotation_service.create_quotation(
        db,
        organisation_id=current_user.organisation_id,
        customer_id=customer.id,
        created_by_user_id=current_user.id,
        quotation_date=now_jdk().date(),
        lines=[
            quotation_service.LineInput(
                product_id=line.product_id,
                quantity=line.quantity,
                unit_of_measure_id=line.unit_of_measure_id,
                unit_price=line.unit_price,
            )
            for line in payload.lines
        ],
        requested_delivery_date=payload.requested_delivery_date,
    )

    audit_service.log_event(
        db,
        action=QUOTATION_CREATED,
        module=SALES_MODULE,
        organisation_id=current_user.organisation_id,
        actor_user_id=current_user.id,
        entity_type="quotation",
        entity_id=quotation.id,
        result="success",
        details=(
            f"number: {quotation.quotation_number}, customer_id: {customer.id}, "
            f"lines: {len(quotation.lines)}, total: {quotation.total_amount} {quotation.currency}, "
            f"price_approval_required: {quotation.price_approval_required}, "
            f"requested_delivery_date: {quotation.requested_delivery_date}"
        ),
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    return _get_visible_quotation(db, quotation.id, current_user)


@router.get("/{quotation_id}/same-day-fg", response_model=SameDayGateOut)
def get_same_day_fg_gate(
    quotation_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> same_day_fg_service.SameDayGate:
    """Read-only same-day Finished Goods gate (Sales S6), evaluated now in
    Kuwait time. Any Admin decision shown is the current S8 feasibility
    record's -- decided via .../feasibility-checks/{id}/decision. Changes
    nothing -- no reservation, no stock movement."""
    quotation = _get_visible_quotation(db, quotation_id, current_user)
    return same_day_fg_service.evaluate_quotation(db, quotation)


@router.get("/{quotation_id}/feasibility", response_model=FeasibilityCalculationOut)
def get_feasibility(
    quotation_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> feasibility_service.FeasibilityCalculation:
    """Read-only 0-2 working-day feasibility calculation (Sales S7),
    evaluated now in Kuwait time. Nothing is stored or changed."""
    quotation = _get_visible_quotation(db, quotation_id, current_user)
    if quotation.requested_delivery_date is None:
        return feasibility_service.FeasibilityCalculation(delivery_window=None, applies=False)
    return feasibility_service.calculate(
        db,
        quotation.organisation_id,
        quotation.requested_delivery_date,
        [
            same_day_fg_service.RequestedQuantity(line.product_id, line.quantity, line.unit_of_measure_id)
            for line in quotation.lines
        ],
    )


# --- Feasibility records (Sales S8) -----------------------------------------


def _check_out(db: Session, record: FeasibilityCheck, quotation: Quotation) -> FeasibilityCheckOut:
    return FeasibilityCheckOut(
        id=record.id,
        quotation_id=record.quotation_id,
        customer_id=record.customer_id,
        requested_delivery_date=record.requested_delivery_date,
        delivery_window=record.delivery_window,
        calculation_basis=record.calculation_basis,
        calculated_at=record.calculated_at,
        result=record.result,
        failed_stage=record.failed_stage,
        reason_codes=json.loads(record.reason_codes),
        stages=json.loads(record.stages),
        state=record.state,
        created_by_user_id=record.created_by_user_id,
        created_at=record.created_at,
        decision_reason=record.decision_reason,
        decided_by_user_id=record.decided_by_user_id,
        decided_at=record.decided_at,
        lines=[FeasibilityCheckLineOut.model_validate(line) for line in record.lines],
        is_current=feasibility_record_service.is_current(db, record, quotation),
    )


def _get_check(db: Session, quotation: Quotation, check_id: int) -> FeasibilityCheck:
    record = (
        db.query(FeasibilityCheck)
        .filter(FeasibilityCheck.id == check_id, FeasibilityCheck.quotation_id == quotation.id)
        .first()
    )
    if record is None:
        raise NotFoundError("Feasibility check not found.")
    return record


@router.post("/{quotation_id}/feasibility-checks", response_model=FeasibilityCheckOut, status_code=status.HTTP_201_CREATED)
def run_feasibility_check(
    quotation_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FeasibilityCheckOut:
    """Runs feasibility now (Kuwait time) and stores the result as a new
    record -- the first check and every re-check alike. Earlier records
    are kept unchanged. Anyone who can see the quotation may run it; only
    Admin decides exceptions."""
    quotation = _get_visible_quotation(db, quotation_id, current_user)
    record = feasibility_record_service.run_check(db, quotation, current_user.id)
    audit_service.log_event(
        db,
        action=FEASIBILITY_RECORDED,
        module=SALES_MODULE,
        organisation_id=current_user.organisation_id,
        actor_user_id=current_user.id,
        entity_type="feasibility_check",
        entity_id=record.id,
        result="success",
        details=(
            f"quotation: {quotation.quotation_number}, window: {record.delivery_window}, "
            f"result: {record.result}, state: {record.state}, reasons: {record.reason_codes}"
        ),
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    return _check_out(db, record, quotation)


@router.get("/{quotation_id}/feasibility-checks", response_model=list[FeasibilityCheckOut])
def list_feasibility_checks(
    quotation_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[FeasibilityCheckOut]:
    """Every stored result for the quotation, newest first -- the full
    decision history."""
    quotation = _get_visible_quotation(db, quotation_id, current_user)
    records = (
        db.query(FeasibilityCheck)
        .filter(FeasibilityCheck.quotation_id == quotation.id)
        .order_by(FeasibilityCheck.id.desc())
        .all()
    )
    return [_check_out(db, record, quotation) for record in records]


@router.get("/{quotation_id}/feasibility-checks/{check_id}", response_model=FeasibilityCheckOut)
def get_feasibility_check(
    quotation_id: int, check_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> FeasibilityCheckOut:
    quotation = _get_visible_quotation(db, quotation_id, current_user)
    return _check_out(db, _get_check(db, quotation, check_id), quotation)


@router.put("/{quotation_id}/feasibility-checks/{check_id}/decision", response_model=FeasibilityCheckOut)
def decide_feasibility_check(
    quotation_id: int,
    check_id: int,
    payload: FeasibilityDecisionRequest,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> FeasibilityCheckOut:
    """Admin/Super Admin only: approve or reject a feasibility exception,
    with a reason. Only on a current record that needed a decision; Admin
    may change an earlier decision. The calculated result is untouched.
    Every decision is audited."""
    quotation = _get_visible_quotation(db, quotation_id, admin)
    record = _get_check(db, quotation, check_id)
    previous = feasibility_record_service.decide(db, record, quotation, payload.decision, payload.reason, admin.id)
    audit_service.log_event(
        db,
        action=FEASIBILITY_DECIDED,
        module=SALES_MODULE,
        organisation_id=admin.organisation_id,
        actor_user_id=admin.id,
        entity_type="feasibility_check",
        entity_id=record.id,
        result="success",
        details=f"state: {previous} -> {record.state}; reason: {payload.reason}; calculated result: {record.result}",
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    return _check_out(db, record, quotation)


# --- Readiness gate (Sales S9) ----------------------------------------------


@router.post("/{quotation_id}/readiness", response_model=QuotationReadinessOut)
def assess_readiness(
    quotation_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> quotation_readiness_service.Readiness:
    """Assesses whether the quotation is commercially and operationally
    ready for the next Sales decision, from current server data, and
    audits the assessment. Not acceptance: the quotation, stock and
    everything else are left unchanged; anything that later needs
    readiness must call this, never trust a client flag."""
    quotation = _get_visible_quotation(db, quotation_id, current_user)
    readiness = quotation_readiness_service.assess(db, quotation)
    audit_service.log_event(
        db,
        action=QUOTATION_READINESS_ASSESSED,
        module=SALES_MODULE,
        organisation_id=current_user.organisation_id,
        actor_user_id=current_user.id,
        entity_type="quotation",
        entity_id=quotation.id,
        result="success",
        details=(
            f"quotation: {quotation.quotation_number}, requested_delivery_date: {quotation.requested_delivery_date}, "
            f"window: {readiness.delivery_window}, feasibility_check: {readiness.feasibility_check_id} "
            f"({readiness.feasibility_state}), commercial_approval_required: {readiness.commercial_approval_required}, "
            f"readiness: {readiness.status}, reasons: {readiness.reason_codes}"
        ),
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    return readiness
