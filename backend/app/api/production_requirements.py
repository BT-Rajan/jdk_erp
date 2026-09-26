"""Production Requirements (Production P1): the Production module's
read-only view of customer demand/shortfall records created at Sales
hand-off, and the one Production action on them -- resolving a
`bom_required` requirement by snapshotting the product's active BOM.

`production:view` to read, `production:manage` to resolve (Admins always
have both). A requirement is demand, never a production command: nothing
here schedules, produces, reserves or moves stock. Sales-side changes
(Admin quantity edits, order cancellation, delivery) move requirements
through their own endpoints and audit them with `audit_changes`."""

from decimal import Decimal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import or_
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.errors import NotFoundError
from app.core.list_query import paginate
from app.models.audit_event import (
    PRODUCTION_MODULE,
    PRODUCTION_REQUIREMENT_BOM_RESOLVED,
    PRODUCTION_REQUIREMENT_CANCELLED,
    PRODUCTION_REQUIREMENT_CREATED,
    PRODUCTION_REQUIREMENT_SATISFIED,
    PRODUCTION_REQUIREMENT_QUANTITY_CHANGED,
    PRODUCTION_REQUIREMENT_REOPENED,
)
from app.models.product import Product
from app.models.production_requirement import (
    REQUIREMENT_ACTIVE,
    REQUIREMENT_BOM_REQUIRED,
    REQUIREMENT_STATUSES,
    ProductionRequirement,
    SalesOrderLineFulfilment,
)
from app.models.sales_order import SalesOrder, SalesOrderLine
from app.models.user import User
from app.schemas.pagination import PaginatedResponse
from app.schemas.production_requirement import ProductionRequirementRowOut
from app.services import (
    audit_service,
    delivery_instruction_service,
    fg_allocation_service,
    production_requirement_service,
    production_scope,
)

router = APIRouter(prefix="/api/production-requirements", tags=["production-requirements"])

_ACTIONS = {
    "created": PRODUCTION_REQUIREMENT_CREATED,
    "quantity_changed": PRODUCTION_REQUIREMENT_QUANTITY_CHANGED,
    "reopened": PRODUCTION_REQUIREMENT_REOPENED,
    "cancelled": PRODUCTION_REQUIREMENT_CANCELLED,
    "satisfied": PRODUCTION_REQUIREMENT_SATISFIED,
}


def audit_changes(
    db: Session, request: Request, user: User, changes: list[production_requirement_service.RequirementChange], order_number: str
) -> None:
    """One audit event per requirement transition, module `production`."""
    for change in changes:
        audit_service.log_event(
            db,
            action=_ACTIONS[change.kind],
            module=PRODUCTION_MODULE,
            organisation_id=user.organisation_id,
            actor_user_id=user.id,
            entity_type="production_requirement",
            entity_id=change.requirement.id,
            result="success",
            details=f"sales_order: {order_number}; {change.details}",
            ip_address=request.client.host if request.client else None,
        )


def _query(db: Session, user: User):
    return (
        db.query(ProductionRequirement)
        .options(selectinload(ProductionRequirement.components))
        .filter(ProductionRequirement.organisation_id == user.organisation_id)
    )


def _row(db: Session, user: User, requirement: ProductionRequirement, can_manage: bool) -> ProductionRequirementRowOut:
    row = ProductionRequirementRowOut.model_validate(requirement)
    order = requirement.sales_order
    line = db.get(SalesOrderLine, requirement.sales_order_line_id)
    fulfilment = (
        db.query(SalesOrderLineFulfilment)
        .filter(SalesOrderLineFulfilment.sales_order_line_id == requirement.sales_order_line_id)
        .first()
    )
    row.sales_order_number = order.order_number if order is not None else None
    row.sales_order_status = order.status if order is not None else None
    row.customer_name = order.customer_name if order is not None else None
    row.product_name = db.query(Product.name).filter(Product.id == requirement.product_id).scalar()
    row.line_number = line.line_number if line is not None else None
    row.ordered_quantity = line.quantity if line is not None else None
    row.covered_quantity = fulfilment.fg_covered_quantity if fulfilment is not None else None
    delivered = delivery_instruction_service.fulfilled_quantity(db, requirement.sales_order_line_id)
    row.delivered_quantity = delivered
    row.required_quantity = (line.quantity - delivered) if line is not None else Decimal("0")
    row.allocated_quantity = fg_allocation_service.line_allocation(db, requirement.sales_order_line_id)
    row.outstanding_quantity = requirement.quantity if requirement.status in REQUIREMENT_ACTIVE else Decimal("0")
    row.can_resolve_bom = can_manage and requirement.status == REQUIREMENT_BOM_REQUIRED
    return row


@router.get("", response_model=PaginatedResponse[ProductionRequirementRowOut])
def list_production_requirements(
    status: str | None = Query(None),
    q: str | None = Query(None, max_length=100),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PaginatedResponse[ProductionRequirementRowOut]:
    """Every requirement of the organisation, newest first. `status`
    filters by state; `q` matches the Sales Order number or product."""
    production_scope.require_permission(db, current_user, production_scope.VIEW)
    query = _query(db, current_user)
    if status in REQUIREMENT_STATUSES:
        query = query.filter(ProductionRequirement.status == status)
    if q:
        query = (
            query.join(SalesOrder, SalesOrder.id == ProductionRequirement.sales_order_id)
            .join(Product, Product.id == ProductionRequirement.product_id)
            .filter(or_(SalesOrder.order_number.ilike(f"%{q}%"), Product.name.ilike(f"%{q}%"), Product.code.ilike(f"%{q}%")))
        )
    rows, pagination = paginate(query.order_by(ProductionRequirement.id.desc()), page, page_size)
    can_manage = production_scope.can_perform(db, current_user, production_scope.MANAGE)
    return PaginatedResponse(data=[_row(db, current_user, r, can_manage) for r in rows], pagination=pagination)


def _get(db: Session, user: User, requirement_id: int) -> ProductionRequirement:
    requirement = _query(db, user).filter(ProductionRequirement.id == requirement_id).first()
    if requirement is None:
        raise NotFoundError("Production requirement not found.")
    return requirement


@router.get("/{requirement_id}", response_model=ProductionRequirementRowOut)
def get_production_requirement(
    requirement_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> ProductionRequirementRowOut:
    production_scope.require_permission(db, current_user, production_scope.VIEW)
    can_manage = production_scope.can_perform(db, current_user, production_scope.MANAGE)
    return _row(db, current_user, _get(db, current_user, requirement_id), can_manage)


@router.post("/{requirement_id}/snapshot-bom", response_model=ProductionRequirementRowOut)
def snapshot_requirement_bom(
    requirement_id: int, request: Request, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> ProductionRequirementRowOut:
    """`bom_required` -> `open`: snapshots the product's active BOM, once
    (its base quantity and each component in the raw material's unit). The
    quantity is unchanged and later BOM edits never reach the snapshot.
    409 if the requirement is not waiting for a BOM or the product still
    has no active BOM. Audited."""
    production_scope.require_permission(db, current_user, production_scope.MANAGE)
    requirement = _get(db, current_user, requirement_id)
    production_requirement_service.snapshot_bom(db, requirement)
    db.refresh(requirement)
    audit_service.log_event(
        db,
        action=PRODUCTION_REQUIREMENT_BOM_RESOLVED,
        module=PRODUCTION_MODULE,
        organisation_id=current_user.organisation_id,
        actor_user_id=current_user.id,
        entity_type="production_requirement",
        entity_id=requirement.id,
        result="success",
        details=(
            f"sales_order: {requirement.sales_order.order_number}; bom_required -> open; bom {requirement.bom_id}, "
            f"base {requirement.bom_base_quantity}, components: "
            + ", ".join(f"{c.raw_material_id}: {c.quantity}" for c in requirement.components)
        ),
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    db.expire_all()
    return _row(db, current_user, _get(db, current_user, requirement_id), True)
