"""Sales Orders (Sales S13). Created only by converting an accepted
quotation (POST /api/quotations/{id}/convert). Every path here is scoped
through the order's customer (S2) -- outside scope is a 404. Every order
is handed off to fulfilment on creation (S14.2), so cancel and change are
Admin only, each with a mandatory reason, and audited (a change with every
old -> new value). Nothing here reserves, produces, moves, bills or
delivers anything."""

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import or_
from sqlalchemy.orm import Session, selectinload

from app.api import production_requirements as production_requirements_api
from app.api.deps import get_current_user, require_admin
from app.core.database import get_db
from app.core.entity_access import register_entity_access_check
from app.core.errors import AccessDeniedError, NotFoundError
from app.core.list_query import paginate
from app.core.roles import ADMIN_ROLES
from app.core.timezone import now_jdk
from app.models.audit_event import SALES_MODULE, SALES_ORDER_CANCELLED, SALES_ORDER_UPDATED
from app.models.customer import Customer
from app.models.production_requirement import ProductionRequirement, SalesOrderLineFulfilment
from app.models.sales_order import HANDED_OFF, SalesOrder
from app.models.user import User
from app.schemas.file import FileOut
from app.schemas.pagination import PaginatedResponse
from app.schemas.production_requirement import LineFulfilmentOut, ProductionRequirementOut
from app.schemas.sales_order import SalesOrderCancelRequest, SalesOrderOut, SalesOrderUpdateRequest
from app.services import (
    audit_service,
    customer_scope,
    delivery_instruction_service,
    production_requirement_service,
    quotation_service,
    sales_document_service,
    sales_order_service,
)

router = APIRouter(prefix="/api/sales-orders", tags=["sales-orders"])


def _scoped_query(db: Session, user: User):
    query = (
        db.query(SalesOrder)
        .options(selectinload(SalesOrder.lines))
        .filter(SalesOrder.organisation_id == user.organisation_id)
    )
    return customer_scope.scope_by_customer(db, user, query, SalesOrder.customer_id)


def _get_visible_order(db: Session, order_id: int, user: User) -> SalesOrder:
    order = _scoped_query(db, user).filter(SalesOrder.id == order_id).first()
    if order is None:
        raise NotFoundError("Sales order not found.")
    return order


def _admin_may_act(order: SalesOrder, user: User) -> bool:
    """S13.1 / S14.2: after hand-off only Admin cancels or changes an order."""
    return order.status == HANDED_OFF and user.role in ADMIN_ROLES


def order_out(db: Session, order: SalesOrder, user: User, *, with_pdf: bool = False) -> SalesOrderOut:
    out = SalesOrderOut.model_validate(order)
    for line in out.lines:
        line.fulfilled_quantity = delivery_instruction_service.fulfilled_quantity(db, line.id)
        line.remaining_quantity = line.quantity - line.fulfilled_quantity
    out.can_cancel = _admin_may_act(order, user)
    out.can_edit = _admin_may_act(order, user)
    if with_pdf:
        record = sales_document_service.latest_pdf(db, sales_document_service.SALES_ORDER_PDF, order.id)
        out.pdf_file = FileOut.model_validate(record) if record is not None else None
    return out


def _audit(db: Session, request: Request, user: User, action: str, order: SalesOrder, details: str) -> None:
    audit_service.log_event(
        db,
        action=action,
        module=SALES_MODULE,
        organisation_id=user.organisation_id,
        actor_user_id=user.id,
        entity_type="sales_order",
        entity_id=order.id,
        result="success",
        details=f"number: {order.order_number}, {details}",
        ip_address=request.client.host if request.client else None,
    )


@router.get("", response_model=PaginatedResponse[SalesOrderOut])
def list_sales_orders(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    q: str | None = Query(None, max_length=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PaginatedResponse[SalesOrderOut]:
    """Scoped server-side through the customer; `q` matches the order
    number or customer name."""
    query = _scoped_query(db, current_user)
    if q:
        query = query.join(Customer, Customer.id == SalesOrder.customer_id).filter(
            or_(SalesOrder.order_number.ilike(f"%{q}%"), Customer.name.ilike(f"%{q}%"))
        )
    orders, pagination = paginate(query.order_by(SalesOrder.id.desc()), page, page_size)
    return PaginatedResponse(data=[order_out(db, o, current_user) for o in orders], pagination=pagination)


@router.get("/{order_id}", response_model=SalesOrderOut)
def get_sales_order(
    order_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> SalesOrderOut:
    return order_out(db, _get_visible_order(db, order_id, current_user), current_user, with_pdf=True)


@router.get("/{order_id}/fulfilment", response_model=list[LineFulfilmentOut])
def get_sales_order_fulfilment(
    order_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[LineFulfilmentOut]:
    """Read-only (S15.2): per line, what Finished Goods covered at hand-off
    and the Production Requirement for any shortfall. Same visibility as
    the order itself. There is no write path here -- the order's
    commercial data is never changed from the production side."""
    order = _get_visible_order(db, order_id, current_user)
    line_numbers = {line.id: line.line_number for line in order.lines}
    requirements = {
        r.sales_order_line_id: r
        for r in db.query(ProductionRequirement).filter(ProductionRequirement.sales_order_id == order.id)
    }
    rows = []
    for fulfilment in (
        db.query(SalesOrderLineFulfilment)
        .filter(SalesOrderLineFulfilment.sales_order_id == order.id)
        .order_by(SalesOrderLineFulfilment.id)
    ):
        out = LineFulfilmentOut.model_validate(fulfilment)
        out.line_number = line_numbers.get(fulfilment.sales_order_line_id)
        requirement = requirements.get(fulfilment.sales_order_line_id)
        if requirement is not None:
            out.production_requirement = ProductionRequirementOut.model_validate(requirement)
        rows.append(out)
    return rows


@router.post("/{order_id}/cancel", response_model=SalesOrderOut)
def cancel_sales_order(
    order_id: int,
    payload: SalesOrderCancelRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SalesOrderOut:
    """Admin only once handed off (every order is, from creation); reason
    mandatory; final."""
    order = _get_visible_order(db, order_id, current_user)
    if current_user.role not in ADMIN_ROLES:
        raise AccessDeniedError("Only Admin can cancel a Sales Order after it has been handed off to fulfilment.")
    sales_order_service.cancel(order, current_user.id, payload.reason)
    _audit(db, request, current_user, SALES_ORDER_CANCELLED, order, f"reason: {payload.reason}")
    # Production P1: its demand is withdrawn -- active requirements are
    # cancelled (kept, never deleted); nothing moves in inventory.
    requirement_changes = production_requirement_service.cancel_for_order(db, order, payload.reason)
    production_requirements_api.audit_changes(db, request, current_user, requirement_changes, order.order_number)
    db.commit()
    db.expire_all()
    return order_out(db, _get_visible_order(db, order_id, current_user), current_user, with_pdf=True)


@router.patch("/{order_id}", response_model=SalesOrderOut)
def update_sales_order(
    order_id: int,
    payload: SalesOrderUpdateRequest,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> SalesOrderOut:
    """Admin/Super Admin only, reason mandatory, handed-off orders only:
    the requested date, quantities and prices (re-validated and re-priced
    on the server). Every change is audited with its old and new value."""
    order = _get_visible_order(db, order_id, admin)
    updates = payload.model_dump(exclude_unset=True)
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
    changes, requirement_changes = sales_order_service.admin_update(
        db,
        order,
        today=now_jdk().date(),
        customer_id=updates.get("customer_id"),
        lines=lines,
        confirm_fulfilment_change=payload.confirm_fulfilment_change,
        **kwargs,
    )
    if changes:
        _audit(db, request, admin, SALES_ORDER_UPDATED, order, f"changes: {'; '.join(changes)}; reason: {payload.reason}")
        production_requirements_api.audit_changes(db, request, admin, requirement_changes, order.order_number)
        # A new Order Confirmation PDF for the changed order (commits).
        sales_document_service.store_sales_order_pdf(db, order, admin.id)
    else:
        db.commit()
    db.expire_all()
    return order_out(db, _get_visible_order(db, order_id, admin), admin, with_pdf=True)


def _check_sales_order_pdf_access(db: Session, user: User, order_id: int) -> bool:
    """An Order Confirmation PDF follows the order's own visibility (customer scope)."""
    return _scoped_query(db, user).filter(SalesOrder.id == order_id).first() is not None


register_entity_access_check(sales_document_service.SALES_ORDER_PDF, _check_sales_order_pdf_access)
