"""Sales Orders (Sales S13). Created only by converting an accepted
quotation (POST /api/quotations/{id}/convert). Every path here is scoped
through the order's customer (S2) -- outside scope is a 404. Cancel: the
owning salesman or their team head, reason required. Change: Admin only,
reason required. All audited. Nothing here reserves, produces, moves,
bills or delivers anything."""

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import or_
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_current_user, require_admin
from app.core.database import get_db
from app.core.errors import AccessDeniedError, NotFoundError
from app.core.list_query import paginate
from app.core.roles import ADMIN_ROLES
from app.core.timezone import now_jdk
from app.models.audit_event import SALES_MODULE, SALES_ORDER_CANCELLED, SALES_ORDER_UPDATED
from app.models.customer import Customer
from app.models.sales_order import OPEN, SalesOrder
from app.models.user import User
from app.schemas.pagination import PaginatedResponse
from app.schemas.sales_order import SalesOrderCancelRequest, SalesOrderOut, SalesOrderUpdateRequest
from app.services import audit_service, customer_scope, quotation_service, sales_order_service

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


def _owner_id(order: SalesOrder) -> int | None:
    return order.customer.assigned_to_user_id if order.customer is not None else None


def _can_cancel(db: Session, order: SalesOrder, user: User) -> bool:
    """S13.1: the owning salesman or their team head, on an open order."""
    if order.status != OPEN:
        return False
    owner_id = _owner_id(order)
    return owner_id == user.id or customer_scope.is_team_head_of(db, user, owner_id)


def order_out(db: Session, order: SalesOrder, user: User) -> SalesOrderOut:
    out = SalesOrderOut.model_validate(order)
    out.can_cancel = _can_cancel(db, order, user)
    out.can_edit = order.status == OPEN and user.role in ADMIN_ROLES
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
    return order_out(db, _get_visible_order(db, order_id, current_user), current_user)


@router.post("/{order_id}/cancel", response_model=SalesOrderOut)
def cancel_sales_order(
    order_id: int,
    payload: SalesOrderCancelRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SalesOrderOut:
    """The owning salesman or their team head; reason mandatory; final."""
    order = _get_visible_order(db, order_id, current_user)
    if order.status == OPEN and not _can_cancel(db, order, current_user):
        raise AccessDeniedError("Only the owning salesman or their team head can cancel this order.")
    sales_order_service.cancel(order, current_user.id, payload.reason)
    _audit(db, request, current_user, SALES_ORDER_CANCELLED, order, f"reason: {payload.reason}")
    db.commit()
    db.expire_all()
    return order_out(db, _get_visible_order(db, order_id, current_user), current_user)


@router.patch("/{order_id}", response_model=SalesOrderOut)
def update_sales_order(
    order_id: int,
    payload: SalesOrderUpdateRequest,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> SalesOrderOut:
    """Admin/Super Admin only, reason mandatory, open orders only. Lines
    are re-validated and re-priced on the server."""
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
    changed = sales_order_service.admin_update(
        db, order, today=now_jdk().date(), customer_id=updates.get("customer_id"), lines=lines, **kwargs
    )
    if changed:
        _audit(
            db,
            request,
            admin,
            SALES_ORDER_UPDATED,
            order,
            f"changed: {', '.join(changed)}; reason: {payload.reason}; total: {order.total_amount} {order.currency}",
        )
    db.commit()
    db.expire_all()
    return order_out(db, _get_visible_order(db, order_id, admin), admin)
