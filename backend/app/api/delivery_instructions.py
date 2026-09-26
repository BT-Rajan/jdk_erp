"""Delivery Instructions (Delivery D2): shipment tranches of a Sales Order,
created manually by warehouse staff. Every route needs the
`inventory:deliver` grant (Admins always have it) and is scoped to the
caller's organisation. Creation, every shipment change (quantity,
pallets) and every state transition (fulfilled, not fulfilled, retried)
are audited."""

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import or_
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.entity_access import register_entity_access_check
from app.core.errors import NotFoundError
from app.core.list_query import paginate
from app.core.timezone import now_jdk
from app.core.roles import ADMIN_ROLES
from app.models.audit_event import (
    DELIVERY_FULFILLED,
    DELIVERY_INSTRUCTION_CREATED,
    DELIVERY_MODULE,
    DELIVERY_NOT_FULFILLED,
    DELIVERY_RETRIED,
    DELIVERY_SHIPMENT_UPDATED,
    SALES_MODULE,
    SALES_ORDER_DELIVERY_STATUS,
)
from app.models.customer import Customer
from app.models.delivery_instruction import DeliveryInstruction, DeliveryInstructionLine
from app.models.sales_order import SalesOrder
from app.models.user import User
from app.schemas.delivery_instruction import (
    DeliverableOrderOut,
    DeliveryInstructionCreateRequest,
    DeliveryInstructionOut,
    DeliveryLinePositionOut,
    DeliveryNotFulfilledRequest,
    DeliveryPositionOut,
    DeliveryShipmentUpdateRequest,
)
from app.schemas.file import FileOut
from app.schemas.pagination import PaginatedResponse
from app.services import audit_service, delivery_instruction_service, inventory_scope, sales_document_service

router = APIRouter(prefix="/api/delivery-instructions", tags=["delivery-instructions"])


def _out(db: Session, instruction: DeliveryInstruction) -> DeliveryInstructionOut:
    """Detail responses carry the latest Delivery Note PDF (list rows do not)."""
    out = DeliveryInstructionOut.model_validate(instruction)
    record = sales_document_service.latest_pdf(db, sales_document_service.DELIVERY_NOTE_PDF, instruction.id)
    out.pdf_file = FileOut.model_validate(record) if record is not None else None
    return out


def _query(db: Session, user: User):
    return (
        db.query(DeliveryInstruction)
        .options(selectinload(DeliveryInstruction.lines))
        .filter(DeliveryInstruction.organisation_id == user.organisation_id)
    )


@router.get("", response_model=PaginatedResponse[DeliveryInstructionOut])
def list_delivery_instructions(
    sales_order_id: int | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PaginatedResponse[DeliveryInstructionOut]:
    inventory_scope.require_permission(db, current_user, inventory_scope.DELIVER)
    query = _query(db, current_user)
    if sales_order_id is not None:
        query = query.filter(DeliveryInstruction.sales_order_id == sales_order_id)
    rows, pagination = paginate(query.order_by(DeliveryInstruction.id.desc()), page, page_size)
    return PaginatedResponse(data=[DeliveryInstructionOut.model_validate(r) for r in rows], pagination=pagination)


@router.get("/eligible-orders", response_model=PaginatedResponse[DeliverableOrderOut])
def list_deliverable_orders(
    q: str | None = Query(None, max_length=100),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PaginatedResponse[DeliverableOrderOut]:
    """Sales Orders that can take a Delivery Instruction now (handed off or
    partially delivered -- the service's one rule), for warehouse staff
    across all customers. `q` matches the order number or customer."""
    inventory_scope.require_permission(db, current_user, inventory_scope.DELIVER)
    query = db.query(SalesOrder).filter(
        SalesOrder.organisation_id == current_user.organisation_id,
        SalesOrder.status.in_(delivery_instruction_service.DELIVERABLE_STATUSES),
    )
    if q:
        query = query.join(Customer, Customer.id == SalesOrder.customer_id).filter(
            or_(SalesOrder.order_number.ilike(f"%{q}%"), Customer.name.ilike(f"%{q}%"))
        )
    rows, pagination = paginate(query.order_by(SalesOrder.id.desc()), page, page_size)
    return PaginatedResponse(data=[DeliverableOrderOut.model_validate(r) for r in rows], pagination=pagination)


@router.get("/position", response_model=DeliveryPositionOut)
def get_delivery_position(
    sales_order_id: int = Query(...), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> DeliveryPositionOut:
    """A Sales Order's cumulative delivery position per line: ordered,
    fulfilled, remaining, the allowance ceiling and what may still be
    delivered. All derived; read-only."""
    inventory_scope.require_permission(db, current_user, inventory_scope.DELIVER)
    order = (
        db.query(SalesOrder)
        .filter(SalesOrder.id == sales_order_id, SalesOrder.organisation_id == current_user.organisation_id)
        .first()
    )
    if order is None:
        raise NotFoundError("Sales order not found.")
    allowance, locked, positions = delivery_instruction_service.order_position(db, order)
    return DeliveryPositionOut(
        sales_order_id=order.id,
        sales_order_number=order.order_number,
        sales_order_status=order.status,
        customer_name=order.customer_name,
        requested_delivery_date=order.requested_delivery_date,
        can_create=order.status in delivery_instruction_service.DELIVERABLE_STATUSES,
        scrap_allowance_percent=allowance,
        allowance_locked=locked,
        lines=[DeliveryLinePositionOut.model_validate(p) for p in positions],
    )


@router.get("/{instruction_id}", response_model=DeliveryInstructionOut)
def get_delivery_instruction(
    instruction_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> DeliveryInstructionOut:
    inventory_scope.require_permission(db, current_user, inventory_scope.DELIVER)
    instruction = _query(db, current_user).filter(DeliveryInstruction.id == instruction_id).first()
    if instruction is None:
        raise NotFoundError("Delivery instruction not found.")
    return _out(db, instruction)


@router.post("", response_model=DeliveryInstructionOut, status_code=status.HTTP_201_CREATED)
def create_delivery_instruction(
    payload: DeliveryInstructionCreateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DeliveryInstructionOut:
    """One shipment tranche of an eligible (handed-off or partially
    delivered) Sales Order; several may exist per order. The order's
    allowance % is locked by its first instruction. Audited."""
    inventory_scope.require_permission(db, current_user, inventory_scope.DELIVER)
    order = (
        db.query(SalesOrder)
        .filter(SalesOrder.id == payload.sales_order_id, SalesOrder.organisation_id == current_user.organisation_id)
        .first()
    )
    if order is None:
        raise NotFoundError("Sales order not found.")
    instruction = delivery_instruction_service.create(
        db,
        order,
        [delivery_instruction_service.LineInput(line.sales_order_line_id, line.quantity) for line in payload.lines],
        current_user.id,
        now_jdk().date(),
    )
    audit_service.log_event(
        db,
        action=DELIVERY_INSTRUCTION_CREATED,
        module=DELIVERY_MODULE,
        organisation_id=current_user.organisation_id,
        actor_user_id=current_user.id,
        entity_type="delivery_instruction",
        entity_id=instruction.id,
        result="success",
        details=(
            f"number: {instruction.delivery_number}, sales_order: {order.order_number}, "
            f"allowance: {instruction.scrap_allowance_percent}%; "
            + "; ".join(f"line {line.sales_order_line_id}: {line.quantity}" for line in instruction.lines)
        ),
        ip_address=request.client.host if request.client else None,
    )
    # The Delivery Note PDF; upload_file is the single commit point.
    sales_document_service.store_delivery_note_pdf(db, instruction, current_user.id)
    db.expire_all()
    return _out(db, _query(db, current_user).filter(DeliveryInstruction.id == instruction.id).one())


def _get_line(db: Session, user: User, instruction_id: int, line_id: int):
    instruction = _query(db, user).filter(DeliveryInstruction.id == instruction_id).first()
    line = (
        db.query(DeliveryInstructionLine)
        .filter(DeliveryInstructionLine.id == line_id, DeliveryInstructionLine.delivery_instruction_id == instruction_id)
        .first()
        if instruction is not None
        else None
    )
    if line is None:
        raise NotFoundError("Delivery instruction line not found.")
    return instruction, line


@router.patch("/{instruction_id}/lines/{line_id}", response_model=DeliveryInstructionOut)
def update_shipment_line(
    instruction_id: int,
    line_id: int,
    payload: DeliveryShipmentUpdateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DeliveryInstructionOut:
    """Changes a pending line's shipment quantity and/or pallet count
    (Delivery D3). Above the order line's remaining permitted quantity
    only an Admin, with a reason. Audited old -> new. Moves no stock."""
    inventory_scope.require_permission(db, current_user, inventory_scope.DELIVER)
    instruction, line = _get_line(db, current_user, instruction_id, line_id)
    updates = payload.model_dump(exclude_unset=True)
    kwargs = {"pallet_count": updates["pallet_count"]} if "pallet_count" in updates else {}
    changes = delivery_instruction_service.record_shipment(
        db,
        instruction,
        line,
        quantity=payload.quantity,
        unit_of_measure_id=payload.unit_of_measure_id,
        override_reason=payload.override_reason,
        is_admin=current_user.role in ADMIN_ROLES,
        **kwargs,
    )
    if changes:
        audit_service.log_event(
            db,
            action=DELIVERY_SHIPMENT_UPDATED,
            module=DELIVERY_MODULE,
            organisation_id=current_user.organisation_id,
            actor_user_id=current_user.id,
            entity_type="delivery_instruction",
            entity_id=instruction.id,
            result="success",
            details=f"number: {instruction.delivery_number}; " + "; ".join(changes),
            ip_address=request.client.host if request.client else None,
        )
        # A new Delivery Note for the changed shipment (commits).
        sales_document_service.store_delivery_note_pdf(db, instruction, current_user.id)
    else:
        db.commit()
    db.expire_all()
    return _out(db, _query(db, current_user).filter(DeliveryInstruction.id == instruction_id).one())


def _get_instruction(db: Session, user: User, instruction_id: int) -> DeliveryInstruction:
    instruction = _query(db, user).filter(DeliveryInstruction.id == instruction_id).first()
    if instruction is None:
        raise NotFoundError("Delivery instruction not found.")
    return instruction


def _audit_transition(db: Session, request: Request, user: User, action: str, instruction: DeliveryInstruction, details: str) -> None:
    audit_service.log_event(
        db,
        action=action,
        module=DELIVERY_MODULE,
        organisation_id=user.organisation_id,
        actor_user_id=user.id,
        entity_type="delivery_instruction",
        entity_id=instruction.id,
        result="success",
        details=f"number: {instruction.delivery_number}, sales_order: {instruction.sales_order_number}; {details}",
        ip_address=request.client.host if request.client else None,
    )


def _reload(db: Session, user: User, instruction_id: int) -> DeliveryInstructionOut:
    db.commit()
    db.expire_all()
    return _out(db, _query(db, user).filter(DeliveryInstruction.id == instruction_id).one())


@router.post("/{instruction_id}/fulfil", response_model=DeliveryInstructionOut)
def fulfil_delivery_instruction(
    instruction_id: int, request: Request, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> DeliveryInstructionOut:
    """pending -> fulfilled, issuing each line's quantity from Finished
    Goods in the same transaction (Delivery D4/D5). Refused unless every
    line is within its order line's remaining permitted quantity (or
    carries an Admin override) and the stock is on hand. A repeated
    request is a 409 and changes nothing."""
    inventory_scope.require_permission(db, current_user, inventory_scope.DELIVER)
    instruction = _get_instruction(db, current_user, instruction_id)
    movements, status_change = delivery_instruction_service.fulfil(db, instruction, current_user.id)
    issued = "; ".join(
        f"line {line.sales_order_line_id}: {line.quantity} (finished goods movement {movement.id})"
        for line, movement in zip(instruction.lines, movements)
    )
    _audit_transition(db, request, current_user, DELIVERY_FULFILLED, instruction, f"pending -> fulfilled; {issued}")
    if status_change is not None:
        audit_service.log_event(
            db,
            action=SALES_ORDER_DELIVERY_STATUS,
            module=SALES_MODULE,
            organisation_id=current_user.organisation_id,
            actor_user_id=current_user.id,
            entity_type="sales_order",
            entity_id=instruction.sales_order_id,
            result="success",
            details=(
                f"number: {instruction.sales_order_number}, status: {status_change[0]} -> {status_change[1]}; "
                f"by delivery instruction {instruction.delivery_number}"
            ),
            ip_address=request.client.host if request.client else None,
        )
    return _reload(db, current_user, instruction_id)


@router.post("/{instruction_id}/not-fulfilled", response_model=DeliveryInstructionOut)
def mark_delivery_not_fulfilled(
    instruction_id: int,
    payload: DeliveryNotFulfilledRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DeliveryInstructionOut:
    """pending -> not_fulfilled with a mandatory reason (Delivery D4)."""
    inventory_scope.require_permission(db, current_user, inventory_scope.DELIVER)
    instruction = _get_instruction(db, current_user, instruction_id)
    delivery_instruction_service.mark_not_fulfilled(db, instruction, current_user.id, payload.reason)
    _audit_transition(db, request, current_user, DELIVERY_NOT_FULFILLED, instruction, f"pending -> not_fulfilled; reason: {instruction.not_fulfilled_reason}")
    return _reload(db, current_user, instruction_id)


@router.post("/{instruction_id}/retry", response_model=DeliveryInstructionOut)
def retry_delivery_instruction(
    instruction_id: int, request: Request, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> DeliveryInstructionOut:
    """not_fulfilled -> pending: attempt the same instruction again (Delivery D4)."""
    inventory_scope.require_permission(db, current_user, inventory_scope.DELIVER)
    instruction = _get_instruction(db, current_user, instruction_id)
    delivery_instruction_service.retry(db, instruction)
    _audit_transition(db, request, current_user, DELIVERY_RETRIED, instruction, "not_fulfilled -> pending")
    return _reload(db, current_user, instruction_id)


def _check_delivery_note_access(db: Session, user: User, instruction_id: int) -> bool:
    """A Delivery Note follows its Delivery Instruction: same organisation
    and the inventory:deliver grant."""
    organisation_id = db.query(DeliveryInstruction.organisation_id).filter(DeliveryInstruction.id == instruction_id).scalar()
    return organisation_id == user.organisation_id and inventory_scope.can_perform(db, user, inventory_scope.DELIVER)


register_entity_access_check(sales_document_service.DELIVERY_NOTE_PDF, _check_delivery_note_access)
