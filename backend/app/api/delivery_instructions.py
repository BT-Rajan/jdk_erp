"""Delivery Instructions (Delivery D2): shipment tranches of a Sales Order,
created manually by warehouse staff. Every route needs the
`inventory:deliver` grant (Admins always have it) and is scoped to the
caller's organisation. Creation is audited. No fulfilment, stock movement,
pallets or Sales Order change yet."""

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.errors import NotFoundError
from app.core.list_query import paginate
from app.core.timezone import now_jdk
from app.models.audit_event import DELIVERY_INSTRUCTION_CREATED, DELIVERY_MODULE
from app.models.delivery_instruction import DeliveryInstruction
from app.models.sales_order import SalesOrder
from app.models.user import User
from app.schemas.delivery_instruction import DeliveryInstructionCreateRequest, DeliveryInstructionOut
from app.schemas.pagination import PaginatedResponse
from app.services import audit_service, delivery_instruction_service, inventory_scope

router = APIRouter(prefix="/api/delivery-instructions", tags=["delivery-instructions"])


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


@router.get("/{instruction_id}", response_model=DeliveryInstructionOut)
def get_delivery_instruction(
    instruction_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> DeliveryInstruction:
    inventory_scope.require_permission(db, current_user, inventory_scope.DELIVER)
    instruction = _query(db, current_user).filter(DeliveryInstruction.id == instruction_id).first()
    if instruction is None:
        raise NotFoundError("Delivery instruction not found.")
    return instruction


@router.post("", response_model=DeliveryInstructionOut, status_code=status.HTTP_201_CREATED)
def create_delivery_instruction(
    payload: DeliveryInstructionCreateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DeliveryInstruction:
    """One shipment tranche of an eligible (handed-off or partially
    delivered) Sales Order; several may exist per order. Copies the
    current Delivery Scrap Allowance % into each line. Audited."""
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
            f"number: {instruction.delivery_number}, sales_order: {order.order_number}; "
            + "; ".join(
                f"line {line.sales_order_line_id}: {line.quantity} (allowance {line.scrap_allowance_percent}%, "
                f"max {line.max_permitted_quantity})"
                for line in instruction.lines
            )
        ),
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    db.expire_all()
    return _query(db, current_user).filter(DeliveryInstruction.id == instruction.id).one()
