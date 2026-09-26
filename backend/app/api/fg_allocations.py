"""Finished Goods allocation and customer reservation (Reservation + FG
Allocation foundation).

- POST /api/fg-allocations/allocate: claim free FG for a Sales Order line
  (`inventory:allocate`);
- POST /api/fg-allocations/release: return a claim to free FG, with a
  reason (Admin only -- S15.1);
  both recalculate the line's Production Requirement in the same
  transaction;
- GET  /api/fg-allocations/products/{product_id}: physical on hand,
  allocated and free FG (`inventory:view`, `allocate` or `deliver`).

Nothing here writes physical stock or an inventory movement. The audit
helpers are shared with the Sales and Delivery endpoints that move
allocations and reservations as part of their own transactions."""

from decimal import Decimal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin
from app.core.database import get_db
from app.core.errors import AccessDeniedError, NotFoundError
from app.models.audit_event import (
    FG_ALLOCATED,
    FG_ALLOCATION_CONSUMED,
    FG_ALLOCATION_RELEASED,
    INVENTORY_MODULE,
    RESERVATION_CHANGED,
    RESERVATION_CREATED,
    RESERVATION_RELEASED,
    SALES_MODULE,
)
from app.models.product import Product
from app.models.sales_order import SalesOrder, SalesOrderLine
from app.models.user import User
from app.api import production_requirements as production_requirements_api
from app.services import (
    audit_service,
    delivery_instruction_service,
    fg_allocation_service,
    inventory_scope,
    production_requirement_service,
    sales_reservation_service,
)

router = APIRouter(prefix="/api/fg-allocations", tags=["fg-allocations"])

_ALLOCATION_ACTIONS = {"allocated": FG_ALLOCATED, "released": FG_ALLOCATION_RELEASED, "consumed": FG_ALLOCATION_CONSUMED}
_RESERVATION_ACTIONS = {
    "created": RESERVATION_CREATED,
    "changed": RESERVATION_CHANGED,
    "released": RESERVATION_RELEASED,
    "fulfilled": RESERVATION_CHANGED,
}


def _plain(value: Decimal) -> str:
    return format(Decimal(value).normalize(), "f")


def audit_allocation_changes(
    db: Session, request: Request, user: User, changes: list[fg_allocation_service.AllocationChange], context: str
) -> None:
    """One `inventory` audit event per claim change: who (actor), when
    (timestamp), the line, before -> after, and the reason if any."""
    for change in changes:
        details = (
            f"{context}; sales_order_line {change.sales_order_line_id}, product {change.product_id}: "
            f"{_plain(change.before)} -> {_plain(change.after)}"
        )
        if change.reason:
            details += f"; reason: {change.reason}"
        audit_service.log_event(
            db,
            action=_ALLOCATION_ACTIONS[change.kind],
            module=INVENTORY_MODULE,
            organisation_id=user.organisation_id,
            actor_user_id=user.id,
            entity_type="sales_order",
            entity_id=change.sales_order_id,
            result="success",
            details=details,
            ip_address=request.client.host if request.client else None,
        )


def audit_reservation_changes(
    db: Session, request: Request, user: User, changes: list[sales_reservation_service.ReservationChange], context: str
) -> None:
    for change in changes:
        reservation = change.reservation
        audit_service.log_event(
            db,
            action=_RESERVATION_ACTIONS[change.kind],
            module=SALES_MODULE,
            organisation_id=user.organisation_id,
            actor_user_id=user.id,
            entity_type="quotation",
            entity_id=reservation.quotation_id,
            result="success",
            details=f"{context}; reservation {change.kind}: {change.details}",
            ip_address=request.client.host if request.client else None,
        )


class AllocateRequest(BaseModel):
    sales_order_line_id: int
    quantity: Decimal = Field(gt=0, max_digits=14, decimal_places=4)


class ReleaseRequest(BaseModel):
    sales_order_line_id: int
    # Omit to release the whole claim.
    quantity: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=4)
    reason: str = Field(min_length=1, max_length=2000)


class AllocationLineOut(BaseModel):
    sales_order_id: int
    sales_order_line_id: int
    product_id: int
    ordered_quantity: Decimal
    allocated_quantity: Decimal
    delivered_quantity: Decimal
    remaining_quantity: Decimal


class ProductAllocationOut(BaseModel):
    product_id: int
    on_hand_quantity: Decimal
    allocated_quantity: Decimal
    free_quantity: Decimal


def _locked_line(db: Session, user: User, line_id: int) -> tuple[SalesOrder, SalesOrderLine]:
    line = db.query(SalesOrderLine).filter(SalesOrderLine.id == line_id).first()
    order = (
        db.query(SalesOrder)
        .filter(SalesOrder.id == line.sales_order_id, SalesOrder.organisation_id == user.organisation_id)
        .with_for_update()
        .first()
        if line is not None
        else None
    )
    if order is None:
        raise NotFoundError("Sales order line not found.")
    return order, line


def _follow_requirement(db: Session, request: Request, user: User, order: SalesOrder, line: SalesOrderLine, delivered: Decimal) -> None:
    """The line's Production Requirement follows the new allocation in the
    same transaction (never for a cancelled order)."""
    change = production_requirement_service.recalculate_line(db, order, line, delivered)
    production_requirements_api.audit_changes(db, request, user, [change] if change else [], order.order_number)


def _line_out(db: Session, order: SalesOrder, line: SalesOrderLine) -> AllocationLineOut:
    delivered = delivery_instruction_service.fulfilled_quantity(db, line.id)
    return AllocationLineOut(
        sales_order_id=order.id,
        sales_order_line_id=line.id,
        product_id=line.product_id,
        ordered_quantity=line.quantity,
        allocated_quantity=fg_allocation_service.line_allocation(db, line.id),
        delivered_quantity=delivered,
        remaining_quantity=line.quantity - delivered,
    )


@router.post("/allocate", response_model=AllocationLineOut)
def allocate_fg(
    payload: AllocateRequest, request: Request, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> AllocationLineOut:
    """Claims free FG for an open order line: at most the free quantity and
    at most what the line still needs. Audited; no stock moves."""
    inventory_scope.require_permission(db, current_user, inventory_scope.ALLOCATE)
    order, line = _locked_line(db, current_user, payload.sales_order_line_id)
    delivered = delivery_instruction_service.fulfilled_quantity(db, line.id, locking=True)
    change = fg_allocation_service.allocate(db, order, line, payload.quantity, delivered)
    audit_allocation_changes(db, request, current_user, [change], f"sales_order: {order.order_number}")
    _follow_requirement(db, request, current_user, order, line, delivered)
    db.commit()
    return _line_out(db, order, line)


@router.post("/release", response_model=AllocationLineOut)
def release_fg_allocation(
    payload: ReleaseRequest, request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)
) -> AllocationLineOut:
    """Admin: returns a line's claim (or part of it) to free FG, with the
    reason. Physical stock is untouched; no production demand is created.
    Audited with actor, time and reason."""
    order, line = _locked_line(db, admin, payload.sales_order_line_id)
    change = fg_allocation_service.release(db, line, payload.quantity, payload.reason)
    if change is not None:
        audit_allocation_changes(db, request, admin, [change], f"sales_order: {order.order_number}")
        delivered = delivery_instruction_service.fulfilled_quantity(db, line.id, locking=True)
        _follow_requirement(db, request, admin, order, line, delivered)
    db.commit()
    return _line_out(db, order, line)


@router.get("/products/{product_id}", response_model=ProductAllocationOut)
def get_product_allocation(
    product_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> ProductAllocationOut:
    if not any(
        inventory_scope.can_perform(db, current_user, action)
        for action in (inventory_scope.VIEW, inventory_scope.ALLOCATE, inventory_scope.DELIVER)
    ):
        raise AccessDeniedError("You do not have permission to do this.")
    product = db.query(Product).filter(Product.id == product_id, Product.organisation_id == current_user.organisation_id).first()
    if product is None:
        raise NotFoundError("Product not found.")
    on_hand, allocated, free = fg_allocation_service.product_position(db, current_user.organisation_id, product_id)
    return ProductAllocationOut(product_id=product_id, on_hand_quantity=on_hand, allocated_quantity=allocated, free_quantity=free)
