"""MRP / Production Planning (P3).

- GET  /api/mrp: what needs to be produced, how much and why -- customer
  demand (Production Requirements) and independent plans, with FG
  position, BOM status, raw-material needs and exceptions. Read-only.
- /api/production-plans: list/read; create (from a requirement, or
  independent), edit a draft, accept (draft -> planned), cancel (reason).

`production:view` reads, `production:manage` changes (Admins always
may). Commercial data (prices, customer terms) is never exposed here.
Nothing here moves inventory, allocates, schedules or creates a
Production Order. Every plan change is audited (module `production`)."""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.errors import NotFoundError, ValidationError
from app.models.audit_event import (
    PRODUCTION_MODULE,
    PRODUCTION_PLAN_CANCELLED,
    PRODUCTION_PLAN_CREATED,
    PRODUCTION_PLAN_PLANNED,
    PRODUCTION_PLAN_UPDATED,
)
from app.models.product import Product
from app.models.production_plan import CUSTOMER_DEMAND, ProductionPlan
from app.models.user import User
from app.services import audit_service, delivery_instruction_service, production_planning_service, production_scope

router = APIRouter(tags=["production-planning"])


class MaterialNeedOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    raw_material_id: int
    raw_material_name: str
    unit_of_measure_id: int
    unit_code: str | None
    required_quantity: Decimal
    on_hand_quantity: Decimal
    committed_quantity: Decimal
    available_quantity: Decimal
    shortage_quantity: Decimal
    unit_mismatch: bool


class MrpRowOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    demand_type: str
    product_id: int
    product_name: str
    unit_of_measure_id: int
    production_requirement_id: int | None
    requirement_status: str | None
    sales_order_id: int | None
    sales_order_number: str | None
    line_number: int | None
    required_by_date: date | None
    required_quantity: Decimal | None
    allocated_quantity: Decimal | None
    outstanding_quantity: Decimal
    fg_on_hand: Decimal
    fg_allocated: Decimal
    fg_free: Decimal
    planned_quantity: Decimal
    proposed_quantity: Decimal
    excess_quantity: Decimal
    plan_ids: list[int]
    plan_status: str
    bom_status: str
    bom_id: int | None
    materials: list[MaterialNeedOut]
    exceptions: list[str]


class MrpOut(BaseModel):
    rows: list[MrpRowOut]
    material_summary: list[MaterialNeedOut]


class PlanComponentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    raw_material_id: int
    quantity: Decimal
    unit_of_measure_id: int


class ProductionPlanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    unit_of_measure_id: int
    planned_quantity: Decimal
    original_quantity: Decimal
    source_type: str
    production_requirement_id: int | None
    additional: bool
    required_by_date: date | None
    notes: str | None
    status: str
    bom_id: int | None
    bom_base_quantity: Decimal | None
    components: list[PlanComponentOut]
    created_by_user_id: int | None
    created_at: datetime
    updated_at: datetime
    planned_at: datetime | None
    cancelled_at: datetime | None
    cancellation_reason: str | None
    # Traceability (read through the requirement).
    sales_order_id: int | None = None
    sales_order_number: str | None = None
    product_name: str | None = None


class PlanCreateRequest(BaseModel):
    source_type: Literal["customer_demand", "independent"]
    production_requirement_id: int | None = None
    product_id: int | None = None
    unit_of_measure_id: int | None = None
    # Customer demand: omit to plan what is not yet planned.
    planned_quantity: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=4)
    additional: bool = False
    required_by_date: date | None = None
    notes: str | None = Field(default=None, max_length=2000)


class PlanUpdateRequest(BaseModel):
    planned_quantity: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=4)
    required_by_date: date | None = None
    notes: str | None = Field(default=None, max_length=2000)


class PlanCancelRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


def _audit(db: Session, request: Request, user: User, action: str, plan: ProductionPlan, details: str) -> None:
    source = f"requirement {plan.production_requirement_id}" if plan.source_type == CUSTOMER_DEMAND else "independent"
    audit_service.log_event(
        db,
        action=action,
        module=PRODUCTION_MODULE,
        organisation_id=user.organisation_id,
        actor_user_id=user.id,
        entity_type="production_plan",
        entity_id=plan.id,
        result="success",
        details=f"plan {plan.id}, product {plan.product_id}, source: {source}; {details}",
        ip_address=request.client.host if request.client else None,
    )


def _out(db: Session, plan: ProductionPlan) -> ProductionPlanOut:
    out = ProductionPlanOut.model_validate(plan)
    out.product_name = db.query(Product.name).filter(Product.id == plan.product_id).scalar()
    if plan.requirement is not None and plan.requirement.sales_order is not None:
        out.sales_order_id = plan.requirement.sales_order_id
        out.sales_order_number = plan.requirement.sales_order.order_number
        out.required_by_date = plan.requirement.required_by_date
    return out


def _get(db: Session, user: User, plan_id: int) -> ProductionPlan:
    plan = (
        db.query(ProductionPlan)
        .options(selectinload(ProductionPlan.components))
        .filter(ProductionPlan.id == plan_id, ProductionPlan.organisation_id == user.organisation_id)
        .first()
    )
    if plan is None:
        raise NotFoundError("Production plan not found.")
    return plan


def _reload(db: Session, user: User, plan_id: int) -> ProductionPlanOut:
    db.commit()
    db.expire_all()
    return _out(db, _get(db, user, plan_id))


@router.get("/api/mrp", response_model=MrpOut)
def get_mrp(
    required_by_from: date | None = Query(None),
    required_by_to: date | None = Query(None),
    product_id: int | None = Query(None),
    demand_type: Literal["customer_demand", "independent"] | None = Query(None),
    plan_status: Literal["unplanned", "partially_planned", "draft", "planned"] | None = Query(None),
    exception: Literal["any", "bom_required", "material_shortage"] | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MrpOut:
    production_scope.require_permission(db, current_user, production_scope.VIEW)
    rows, summary = production_planning_service.mrp_rows(
        db, current_user.organisation_id, lambda line_id: delivery_instruction_service.fulfilled_quantity(db, line_id)
    )
    if required_by_from is not None:
        rows = [r for r in rows if r.required_by_date is not None and r.required_by_date >= required_by_from]
    if required_by_to is not None:
        rows = [r for r in rows if r.required_by_date is not None and r.required_by_date <= required_by_to]
    if product_id is not None:
        rows = [r for r in rows if r.product_id == product_id]
    if demand_type is not None:
        rows = [r for r in rows if r.demand_type == demand_type]
    if plan_status is not None:
        rows = [r for r in rows if r.plan_status == plan_status]
    if exception == "any":
        rows = [r for r in rows if r.exceptions]
    elif exception is not None:
        rows = [r for r in rows if exception in r.exceptions]
    rows.sort(key=lambda r: (r.required_by_date is None, r.required_by_date or date.max, r.product_name))
    return MrpOut(
        rows=[MrpRowOut.model_validate(r) for r in rows],
        material_summary=[MaterialNeedOut.model_validate(m) for m in summary],
    )


@router.get("/api/production-plans", response_model=list[ProductionPlanOut])
def list_production_plans(
    status_filter: Literal["draft", "planned", "cancelled"] | None = Query(None, alias="status"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ProductionPlanOut]:
    production_scope.require_permission(db, current_user, production_scope.VIEW)
    query = (
        db.query(ProductionPlan)
        .options(selectinload(ProductionPlan.components))
        .filter(ProductionPlan.organisation_id == current_user.organisation_id)
    )
    if status_filter is not None:
        query = query.filter(ProductionPlan.status == status_filter)
    return [_out(db, p) for p in query.order_by(ProductionPlan.id.desc()).limit(500)]


@router.get("/api/production-plans/{plan_id}", response_model=ProductionPlanOut)
def get_production_plan(plan_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ProductionPlanOut:
    production_scope.require_permission(db, current_user, production_scope.VIEW)
    return _out(db, _get(db, current_user, plan_id))


@router.post("/api/production-plans", response_model=ProductionPlanOut, status_code=status.HTTP_201_CREATED)
def create_production_plan(
    payload: PlanCreateRequest, request: Request, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> ProductionPlanOut:
    """A draft plan. Customer demand: for one active requirement (quantity
    defaults to its unplanned demand; `additional` for a further plan).
    Independent: an explicit product and quantity."""
    production_scope.require_permission(db, current_user, production_scope.MANAGE)
    if payload.source_type == CUSTOMER_DEMAND:
        if payload.production_requirement_id is None:
            raise ValidationError("Choose the requirement to plan for.", fields={"production_requirement_id": "Required."})
        plan = production_planning_service.create_customer_plan(
            db, current_user.organisation_id, payload.production_requirement_id, payload.planned_quantity,
            payload.additional, payload.notes, current_user.id,
        )
    else:
        if payload.product_id is None or payload.planned_quantity is None:
            raise ValidationError(
                "An independent plan needs a product and a quantity.",
                fields={"product_id": "Required.", "planned_quantity": "Required."},
            )
        plan = production_planning_service.create_independent_plan(
            db, current_user.organisation_id, payload.product_id, payload.planned_quantity, payload.unit_of_measure_id,
            payload.required_by_date, payload.notes, current_user.id,
        )
    _audit(
        db, request, current_user, PRODUCTION_PLAN_CREATED, plan,
        f"planned_quantity {plan.planned_quantity}; bom {plan.bom_id or 'required'}" + ("; additional plan" if plan.additional else ""),
    )
    return _reload(db, current_user, plan.id)


@router.patch("/api/production-plans/{plan_id}", response_model=ProductionPlanOut)
def update_production_plan(
    plan_id: int, payload: PlanUpdateRequest, request: Request, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> ProductionPlanOut:
    """Draft only; every change audited old -> new (original_quantity stays)."""
    production_scope.require_permission(db, current_user, production_scope.MANAGE)
    plan = _get(db, current_user, plan_id)
    changes = production_planning_service.update_plan(db, plan, payload.model_dump(exclude_unset=True))
    if changes:
        _audit(db, request, current_user, PRODUCTION_PLAN_UPDATED, plan, "; ".join(changes))
    return _reload(db, current_user, plan_id)


@router.post("/api/production-plans/{plan_id}/plan", response_model=ProductionPlanOut)
def accept_production_plan(plan_id: int, request: Request, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ProductionPlanOut:
    """draft -> planned: an accepted production plan (not a Production Order)."""
    production_scope.require_permission(db, current_user, production_scope.MANAGE)
    plan = _get(db, current_user, plan_id)
    production_planning_service.accept_plan(db, plan)
    _audit(db, request, current_user, PRODUCTION_PLAN_PLANNED, plan, f"draft -> planned; quantity {plan.planned_quantity}")
    return _reload(db, current_user, plan_id)


@router.post("/api/production-plans/{plan_id}/cancel", response_model=ProductionPlanOut)
def cancel_production_plan(
    plan_id: int, payload: PlanCancelRequest, request: Request, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> ProductionPlanOut:
    production_scope.require_permission(db, current_user, production_scope.MANAGE)
    plan = _get(db, current_user, plan_id)
    previous = production_planning_service.cancel_plan(db, plan, payload.reason)
    _audit(db, request, current_user, PRODUCTION_PLAN_CANCELLED, plan, f"{previous} -> cancelled; reason: {payload.reason.strip()}")
    return _reload(db, current_user, plan_id)
