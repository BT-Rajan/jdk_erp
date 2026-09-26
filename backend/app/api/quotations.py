"""Quotation data foundation (Sales S4): create a draft quotation and read
it back. Every path is scoped through the quotation's customer
(app/services/customer_scope.py, Sales S2) -- a quotation whose customer
is outside the caller's scope is a 404, exactly like the customer
itself. There is no quotation-specific ownership or permission key."""

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.errors import NotFoundError, ValidationError
from app.core.list_query import paginate
from app.core.timezone import now_jdk
from app.models.audit_event import QUOTATION_CREATED, SALES_MODULE
from app.models.quotation import Quotation
from app.models.user import User
from app.schemas.pagination import PaginatedResponse
from app.schemas.quotation import QuotationCreateRequest, QuotationLineOut, QuotationOut
from app.services import audit_service, customer_scope, quotation_service

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


@router.get("", response_model=PaginatedResponse[QuotationOut])
def list_quotations(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PaginatedResponse[QuotationOut]:
    query = _scoped_query(db, current_user).order_by(Quotation.id.desc())
    quotations, pagination = paginate(query, page, page_size)
    return PaginatedResponse(data=[QuotationOut.model_validate(q) for q in quotations], pagination=pagination)


@router.get("/{quotation_id}", response_model=QuotationOut)
def get_quotation(
    quotation_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> Quotation:
    return _get_visible_quotation(db, quotation_id, current_user)


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
            f"price_approval_required: {quotation.price_approval_required}"
        ),
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    return _get_visible_quotation(db, quotation.id, current_user)
