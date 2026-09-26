"""Production Orders (P5): production work formally issued to the factory.

- GET  /api/production-orders (status / date filters) and /{id} (with the
  BOM snapshot, raw-material requirements, traceability Production Order
  -> Schedule -> Plan -> source demand, and audit history);
- POST /api/production-orders: a draft from a schedule entry;
- PATCH /{id}: quantity / notes while draft;
- POST /{id}/issue: validated issue with the production basis snapshot;
- POST /{id}/cancel: with a reason.

`production:view` reads, `production:manage` changes. No commercial data
(prices, customer terms) is exposed. Nothing here moves inventory."""

from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.errors import NotFoundError
from app.models.audit_event import (
    PRODUCTION_MODULE,
    PRODUCTION_ORDER_CANCELLED,
    PRODUCTION_ORDER_CREATED,
    PRODUCTION_ORDER_ISSUED,
    PRODUCTION_ORDER_UPDATED,
    PRODUCTION_RECORDED,
    PRODUCTION_STARTED,
    AuditEvent,
)
from app.models.machine import Machine
from app.models.product import Product
from app.models.production_line import ProductionLine
from app.models.production_execution import ProductionExecution
from app.models.production_order import ORDER_STATUSES, ProductionOrder
from app.models.raw_material import RawMaterial
from app.models.sales_order import SalesOrderLine
from app.models.user import User
from app.services import (
    audit_service,
    fg_allocation_service,
    inventory_service,
    production_execution_service,
    production_order_service,
    production_schedule_service,
    production_scope,
)

router = APIRouter(prefix="/api/production-orders", tags=["production-orders"])


class ComponentOut(BaseModel):
    raw_material_id: int
    raw_material_name: str
    quantity: Decimal
    unit_of_measure_id: int
    required_quantity: Decimal
    # Execution (P6): consumed so far by this order; on hand now (read from
    # Raw Material Inventory, detail only).
    consumed_quantity: Decimal = Decimal("0")
    available_quantity: Decimal | None = None


class ExecutionMaterialOut(BaseModel):
    raw_material_id: int
    quantity: Decimal
    unit_of_measure_id: int
    stock_movement_id: int | None


class ExecutionOut(BaseModel):
    id: int
    sequence: int
    produced_quantity: Decimal
    unit_of_measure_id: int
    executed_at: datetime
    notes: str | None
    status: str
    recorded_by_user_id: int | None
    fg_movement_id: int | None
    materials: list[ExecutionMaterialOut]


class HistoryOut(BaseModel):
    action: str
    actor_user_id: int | None
    created_at: datetime
    details: str | None


class ProductionOrderOut(BaseModel):
    id: int
    order_number: str
    status: str
    product_id: int
    product_name: str | None
    unit_of_measure_id: int
    quantity: Decimal
    machine_id: int
    machine_name: str | None
    production_line_id: int | None
    production_line_name: str | None
    scheduled_date: date
    notes: str | None
    bom_id: int | None
    bom_base_quantity: Decimal | None
    components: list[ComponentOut]
    production_plan_id: int
    plan_source_type: str
    production_schedule_entry_id: int
    production_requirement_id: int | None
    sales_order_id: int | None
    sales_order_number: str | None
    sales_order_line_number: int | None
    required_by_date: date | None
    created_by_user_id: int | None
    created_at: datetime
    issued_at: datetime | None
    issued_by_user_id: int | None
    cancelled_at: datetime | None
    cancellation_reason: str | None
    # Execution (P6): produced is always the sum of posted executions.
    produced_quantity: Decimal = Decimal("0")
    remaining_quantity: Decimal = Decimal("0")
    started_at: datetime | None = None
    # The product's Finished Goods position, read from Inventory (detail only).
    fg_on_hand_quantity: Decimal | None = None
    fg_free_quantity: Decimal | None = None
    executions: list[ExecutionOut] = []
    history: list[HistoryOut] = []


class RecordRequest(BaseModel):
    produced_quantity: Decimal = Field(gt=0, max_digits=14, decimal_places=4)
    executed_at: datetime | None = None
    notes: str | None = Field(default=None, max_length=2000)
    # Sent by the client once per submission: a retry returns the posted record.
    client_reference: str | None = Field(default=None, max_length=64)


class CreateRequest(BaseModel):
    production_schedule_entry_id: int
    # Omit to take what the schedule entry still has without an order.
    quantity: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=4)
    notes: str | None = Field(default=None, max_length=2000)


class UpdateRequest(BaseModel):
    quantity: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=4)
    notes: str | None = Field(default=None, max_length=2000)


class CancelRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


def _out(db: Session, order: ProductionOrder, with_history: bool = False) -> ProductionOrderOut:
    plan = order.plan
    requirement = plan.requirement if plan is not None else None
    order_row = requirement.sales_order if requirement is not None else None
    line = db.get(SalesOrderLine, requirement.sales_order_line_id) if requirement is not None else None
    machine = db.get(Machine, order.machine_id)
    production_line = db.get(ProductionLine, machine.production_line_id) if machine is not None else None
    executions = (
        db.query(ProductionExecution)
        .options(selectinload(ProductionExecution.materials))
        .filter(ProductionExecution.production_order_id == order.id)
        .order_by(ProductionExecution.sequence)
        .all()
    )
    consumed: dict[int, Decimal] = {}
    for execution in executions:
        for m in execution.materials:
            consumed[m.raw_material_id] = consumed.get(m.raw_material_id, Decimal("0")) + m.quantity
    components = []
    for c in order.components:
        material = db.get(RawMaterial, c.raw_material_id)
        components.append(
            ComponentOut(
                raw_material_id=c.raw_material_id,
                raw_material_name=material.name if material else f"#{c.raw_material_id}",
                quantity=c.quantity,
                unit_of_measure_id=c.unit_of_measure_id,
                required_quantity=c.required_quantity,
                consumed_quantity=consumed.get(c.raw_material_id, Decimal("0")),
                available_quantity=inventory_service.get_organisation_quantity_on_hand(
                    db, organisation_id=order.organisation_id, raw_material_id=c.raw_material_id
                )
                if with_history
                else None,
            )
        )
    produced = production_execution_service.produced_quantity(db, order.id)
    fg_on_hand = fg_free = None
    if with_history:
        fg_on_hand, _, fg_free = fg_allocation_service.product_position(db, order.organisation_id, order.product_id)
    history = []
    if with_history:
        history = [
            HistoryOut(action=e.action, actor_user_id=e.actor_user_id, created_at=e.created_at, details=e.details)
            for e in db.query(AuditEvent)
            .filter(AuditEvent.entity_type == "production_order", AuditEvent.entity_id == order.id)
            .order_by(AuditEvent.id)
        ]
    return ProductionOrderOut(
        id=order.id,
        order_number=order.order_number,
        status=order.status,
        product_id=order.product_id,
        product_name=db.query(Product.name).filter(Product.id == order.product_id).scalar(),
        unit_of_measure_id=order.unit_of_measure_id,
        quantity=order.quantity,
        machine_id=order.machine_id,
        machine_name=machine.name if machine else None,
        production_line_id=production_line.id if production_line else None,
        production_line_name=production_line.name if production_line else None,
        scheduled_date=order.scheduled_date,
        notes=order.notes,
        bom_id=order.bom_id,
        bom_base_quantity=order.bom_base_quantity,
        components=components,
        production_plan_id=order.production_plan_id,
        plan_source_type=plan.source_type,
        production_schedule_entry_id=order.production_schedule_entry_id,
        production_requirement_id=plan.production_requirement_id,
        sales_order_id=order_row.id if order_row else None,
        sales_order_number=order_row.order_number if order_row else None,
        sales_order_line_number=line.line_number if line else None,
        required_by_date=production_schedule_service.required_by(plan),
        created_by_user_id=order.created_by_user_id,
        created_at=order.created_at,
        issued_at=order.issued_at,
        issued_by_user_id=order.issued_by_user_id,
        cancelled_at=order.cancelled_at,
        cancellation_reason=order.cancellation_reason,
        produced_quantity=produced,
        remaining_quantity=max(order.quantity - produced, Decimal("0")),
        started_at=order.started_at,
        fg_on_hand_quantity=fg_on_hand,
        fg_free_quantity=fg_free,
        executions=[
            ExecutionOut(
                id=e.id,
                sequence=e.sequence,
                produced_quantity=e.produced_quantity,
                unit_of_measure_id=e.unit_of_measure_id,
                executed_at=e.executed_at,
                notes=e.notes,
                status=e.status,
                recorded_by_user_id=e.recorded_by_user_id,
                fg_movement_id=e.fg_movement_id,
                materials=[
                    ExecutionMaterialOut(
                        raw_material_id=m.raw_material_id, quantity=m.quantity, unit_of_measure_id=m.unit_of_measure_id,
                        stock_movement_id=m.stock_movement_id,
                    )
                    for m in e.materials
                ],
            )
            for e in executions
        ]
        if with_history
        else [],
        history=history,
    )


def _get(db: Session, user: User, order_id: int) -> ProductionOrder:
    order = (
        db.query(ProductionOrder)
        .options(selectinload(ProductionOrder.components))
        .filter(ProductionOrder.id == order_id, ProductionOrder.organisation_id == user.organisation_id)
        .first()
    )
    if order is None:
        raise NotFoundError("Production order not found.")
    return order


def _audit(db: Session, request: Request, user: User, action: str, order: ProductionOrder, details: str) -> None:
    audit_service.log_event(
        db,
        action=action,
        module=PRODUCTION_MODULE,
        organisation_id=user.organisation_id,
        actor_user_id=user.id,
        entity_type="production_order",
        entity_id=order.id,
        result="success",
        details=f"number: {order.order_number}, plan {order.production_plan_id}, schedule entry {order.production_schedule_entry_id}; {details}",
        ip_address=request.client.host if request.client else None,
    )


def _reload(db: Session, user: User, order_id: int) -> ProductionOrderOut:
    db.commit()
    db.expire_all()
    return _out(db, _get(db, user, order_id), with_history=True)


@router.get("", response_model=list[ProductionOrderOut])
def list_production_orders(
    status_filter: str | None = Query(None, alias="status"),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    product_id: int | None = Query(None),
    q: str | None = Query(None, max_length=30),
    production_line_id: int | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ProductionOrderOut]:
    """Filters: status, scheduled date range, product, order number (`q`)
    and production line (through the machine)."""
    production_scope.require_view_or_execute(db, current_user)
    query = (
        db.query(ProductionOrder)
        .options(selectinload(ProductionOrder.components))
        .filter(ProductionOrder.organisation_id == current_user.organisation_id)
    )
    if status_filter in ORDER_STATUSES:
        query = query.filter(ProductionOrder.status == status_filter)
    if date_from is not None:
        query = query.filter(ProductionOrder.scheduled_date >= date_from)
    if date_to is not None:
        query = query.filter(ProductionOrder.scheduled_date <= date_to)
    if product_id is not None:
        query = query.filter(ProductionOrder.product_id == product_id)
    if q:
        query = query.filter(ProductionOrder.order_number.ilike(f"%{q.strip()}%"))
    if production_line_id is not None:
        query = query.filter(
            ProductionOrder.machine_id.in_(db.query(Machine.id).filter(Machine.production_line_id == production_line_id))
        )
    orders = query.order_by(ProductionOrder.scheduled_date.desc(), ProductionOrder.id.desc()).limit(500)
    return [_out(db, o) for o in orders]


@router.get("/{order_id}", response_model=ProductionOrderOut)
def get_production_order(order_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ProductionOrderOut:
    production_scope.require_view_or_execute(db, current_user)
    return _out(db, _get(db, current_user, order_id), with_history=True)


@router.post("", response_model=ProductionOrderOut, status_code=status.HTTP_201_CREATED)
def create_production_order(
    payload: CreateRequest, request: Request, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> ProductionOrderOut:
    production_scope.require_permission(db, current_user, production_scope.MANAGE)
    order = production_order_service.create_draft(
        db, current_user.organisation_id, payload.production_schedule_entry_id, payload.quantity, payload.notes, current_user.id
    )
    _audit(db, request, current_user, PRODUCTION_ORDER_CREATED, order, f"draft; quantity {order.quantity}")
    return _reload(db, current_user, order.id)


@router.patch("/{order_id}", response_model=ProductionOrderOut)
def update_production_order(
    order_id: int, payload: UpdateRequest, request: Request, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> ProductionOrderOut:
    production_scope.require_permission(db, current_user, production_scope.MANAGE)
    order = _get(db, current_user, order_id)
    changes = production_order_service.update_draft(db, order, payload.model_dump(exclude_unset=True))
    if changes:
        _audit(db, request, current_user, PRODUCTION_ORDER_UPDATED, order, "; ".join(changes))
    return _reload(db, current_user, order_id)


@router.post("/{order_id}/issue", response_model=ProductionOrderOut)
def issue_production_order(order_id: int, request: Request, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ProductionOrderOut:
    production_scope.require_permission(db, current_user, production_scope.MANAGE)
    order = _get(db, current_user, order_id)
    production_order_service.issue(db, order, current_user.id)
    db.refresh(order)
    _audit(
        db, request, current_user, PRODUCTION_ORDER_ISSUED, order,
        f"draft -> issued; quantity {order.quantity}, {order.scheduled_date.isoformat()}, machine {order.machine_id}, "
        f"bom {order.bom_id} base {order.bom_base_quantity}: "
        + ", ".join(f"material {c.raw_material_id} {c.required_quantity}" for c in order.components),
    )
    return _reload(db, current_user, order_id)


@router.post("/{order_id}/cancel", response_model=ProductionOrderOut)
def cancel_production_order(
    order_id: int, payload: CancelRequest, request: Request, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> ProductionOrderOut:
    production_scope.require_permission(db, current_user, production_scope.MANAGE)
    order = _get(db, current_user, order_id)
    previous = production_order_service.cancel(db, order, payload.reason)
    _audit(db, request, current_user, PRODUCTION_ORDER_CANCELLED, order, f"{previous} -> cancelled; reason: {payload.reason.strip()}")
    return _reload(db, current_user, order_id)


@router.post("/{order_id}/start", response_model=ProductionOrderOut)
def start_production_order(order_id: int, request: Request, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ProductionOrderOut:
    """issued -> in_progress (P6). Posts nothing."""
    production_scope.require_permission(db, current_user, production_scope.EXECUTE)
    order = production_execution_service.start(db, current_user.organisation_id, order_id, current_user.id)
    _audit(db, request, current_user, PRODUCTION_STARTED, order, "issued -> in_progress")
    return _reload(db, current_user, order_id)


@router.post("/{order_id}/executions", response_model=ProductionOrderOut, status_code=status.HTTP_201_CREATED)
def record_production(
    order_id: int, payload: RecordRequest, request: Request, response: Response,
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
) -> ProductionOrderOut:
    """Record Production (P6): the actual quantity produced. Consumes the
    raw materials from the order's BOM snapshot and receives the output
    into Finished Goods, atomically. A retry with the same
    `client_reference` returns the posted record (200) without posting again."""
    production_scope.require_permission(db, current_user, production_scope.EXECUTE)
    before = db.query(ProductionOrder.status).filter(ProductionOrder.id == order_id).scalar()
    execution, created = production_execution_service.record(
        db, current_user.organisation_id, order_id, payload.produced_quantity, payload.executed_at, payload.notes,
        payload.client_reference, current_user.id,
    )
    if not created:
        response.status_code = status.HTTP_200_OK
        return _out(db, _get(db, current_user, order_id), with_history=True)
    order = _get(db, current_user, order_id)
    _audit(
        db, request, current_user, PRODUCTION_RECORDED, order,
        f"execution {execution.sequence}: produced {execution.produced_quantity} (FG movement {execution.fg_movement_id}); "
        + ", ".join(f"material {m.raw_material_id} -{m.quantity} (movement {m.stock_movement_id})" for m in execution.materials)
        + f"; {before} -> {order.status}",
    )
    return _reload(db, current_user, order_id)
