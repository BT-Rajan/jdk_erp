"""MRP / Production Planning (P3): "what do we need to produce, how much, and
why?" -- a planning layer only.

It reads existing sources and never writes them:
- customer demand: active Production Requirements (their quantity is the
  current uncovered demand, ordered - delivered - allocated);
- Finished Goods: physical on hand, allocated and free
  (fg_allocation_service.product_position);
- BOM: the snapshot kept on the requirement or plan, else the product's
  active BOM; component needs via bom_service.required_quantity, each in
  its raw material's own unit (no conversion is invented);
- raw materials: on hand via inventory_service (no raw-material
  commitment exists in this ERP, so committed is always 0).

It writes only Production Plans (production_plan.py). No inventory
movement, no allocation, no Production Order, no schedule, and no change
to Sales Orders or Production Requirements."""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.models.bom import ACTIVE, Bom, BomComponent
from app.models.product import Product
from app.models.production_plan import (
    CUSTOMER_DEMAND,
    INDEPENDENT,
    PLAN_ACTIVE,
    PLAN_CANCELLED,
    PLAN_DRAFT,
    PLAN_PLANNED,
    ProductionPlan,
    ProductionPlanComponent,
)
from app.models.production_requirement import REQUIREMENT_ACTIVE, ProductionRequirement
from app.models.raw_material import RawMaterial
from app.models.sales_order import SalesOrderLine
from app.models.unit import UnitOfMeasure
from app.services import bom_service, fg_allocation_service, inventory_service

_ZERO = Decimal("0")


def _plain(value: Decimal) -> str:
    return format(Decimal(value).normalize(), "f")


# --- BOM snapshot ---------------------------------------------------------------


def _snapshot_from_bom(db: Session, plan: ProductionPlan) -> None:
    bom = (
        db.query(Bom)
        .filter(Bom.organisation_id == plan.organisation_id, Bom.product_id == plan.product_id, Bom.status == ACTIVE)
        .first()
    )
    if bom is None:
        return
    plan.bom_id, plan.bom_base_quantity = bom.id, bom.base_quantity
    for component in db.query(BomComponent).filter(BomComponent.bom_id == bom.id).order_by(BomComponent.id):
        material = db.get(RawMaterial, component.raw_material_id)
        plan.components.append(
            ProductionPlanComponent(raw_material_id=material.id, quantity=component.quantity, unit_of_measure_id=material.unit_of_measure_id)
        )


def _snapshot(db: Session, plan: ProductionPlan, requirement: ProductionRequirement | None) -> None:
    """The planning basis, taken once: the requirement's own snapshot if it
    has one, else the product's active BOM (none -> BOM required)."""
    if requirement is not None and requirement.bom_id is not None:
        plan.bom_id, plan.bom_base_quantity = requirement.bom_id, requirement.bom_base_quantity
        for component in requirement.components:
            plan.components.append(
                ProductionPlanComponent(
                    raw_material_id=component.raw_material_id, quantity=component.quantity, unit_of_measure_id=component.unit_of_measure_id
                )
            )
        return
    _snapshot_from_bom(db, plan)


# --- Plans ------------------------------------------------------------------------


def _active_plans(db: Session, requirement_id: int) -> list[ProductionPlan]:
    return (
        db.query(ProductionPlan)
        .filter(ProductionPlan.production_requirement_id == requirement_id, ProductionPlan.status.in_(PLAN_ACTIVE))
        .order_by(ProductionPlan.id)
        .all()
    )


def _positive(quantity: Decimal | None) -> Decimal:
    if quantity is None or quantity <= _ZERO:
        raise ValidationError("Plan a positive quantity.", fields={"planned_quantity": "Must be greater than zero."})
    return quantity


def create_customer_plan(
    db: Session, organisation_id: int, requirement_id: int, quantity: Decimal | None, additional: bool, notes: str | None, user_id: int
) -> ProductionPlan:
    """A plan for one active Production Requirement. The quantity defaults
    to what is not yet planned of its uncovered demand; it may be set
    higher on purpose (the excess is free production). A second active plan
    for the same requirement must be asked for (`additional`)."""
    requirement = (
        db.query(ProductionRequirement)
        .filter(ProductionRequirement.id == requirement_id, ProductionRequirement.organisation_id == organisation_id)
        .with_for_update()
        .first()
    )
    if requirement is None:
        raise NotFoundError("Production requirement not found.")
    if requirement.status not in REQUIREMENT_ACTIVE:
        raise ConflictError(
            f"This requirement is {requirement.status}: there is no customer demand to plan. Plan independent production instead."
        )
    existing = _active_plans(db, requirement.id)
    if existing and not additional:
        raise ConflictError("This demand already has a production plan. Create an additional plan explicitly if it is intended.")
    if quantity is None:
        unplanned = requirement.quantity - sum((p.planned_quantity for p in existing), _ZERO)
        if unplanned <= _ZERO:
            raise ValidationError(
                "This demand is already fully planned; enter the quantity for an additional plan.",
                fields={"planned_quantity": "Required."},
            )
        quantity = unplanned
    quantity = _positive(quantity)
    plan = ProductionPlan(
        organisation_id=organisation_id,
        product_id=requirement.product_id,
        unit_of_measure_id=requirement.unit_of_measure_id,
        planned_quantity=quantity,
        original_quantity=quantity,
        source_type=CUSTOMER_DEMAND,
        production_requirement_id=requirement.id,
        additional=bool(existing),
        notes=(notes or "").strip() or None,
        status=PLAN_DRAFT,
        created_by_user_id=user_id,
    )
    _snapshot(db, plan, requirement)
    db.add(plan)
    db.flush()
    return plan


def create_independent_plan(
    db: Session,
    organisation_id: int,
    product_id: int,
    quantity: Decimal,
    unit_of_measure_id: int | None,
    required_by_date: date | None,
    notes: str | None,
    user_id: int,
) -> ProductionPlan:
    """Production with no customer behind it: an explicit product and
    quantity in the product's own unit. No Sales Order or requirement."""
    product = db.query(Product).filter(Product.id == product_id, Product.organisation_id == organisation_id).first()
    if product is None or not product.is_active:
        raise ValidationError("Choose an active product.", fields={"product_id": "Invalid product."})
    if unit_of_measure_id is not None and unit_of_measure_id != product.unit_of_measure_id:
        raise ValidationError(
            "Plan in the product's own unit; nothing is converted.", fields={"unit_of_measure_id": "Must be the product's unit."}
        )
    quantity = _positive(quantity)
    plan = ProductionPlan(
        organisation_id=organisation_id,
        product_id=product.id,
        unit_of_measure_id=product.unit_of_measure_id,
        planned_quantity=quantity,
        original_quantity=quantity,
        source_type=INDEPENDENT,
        required_by_date=required_by_date,
        notes=(notes or "").strip() or None,
        status=PLAN_DRAFT,
        created_by_user_id=user_id,
    )
    _snapshot(db, plan, None)
    db.add(plan)
    db.flush()
    return plan


def update_plan(db: Session, plan: ProductionPlan, updates: dict) -> list[str]:
    """Draft only: quantity, notes, and (independent only) required-by.
    Returns the changes as "field: old -> new"."""
    if plan.status != PLAN_DRAFT:
        raise ConflictError(f"Only a draft plan can be changed (this one is {plan.status}).")
    changes = []
    if "planned_quantity" in updates:
        quantity = _positive(updates["planned_quantity"])
        if quantity != plan.planned_quantity:
            changes.append(f"planned_quantity: {_plain(plan.planned_quantity)} -> {_plain(quantity)}")
            plan.planned_quantity = quantity
    if "required_by_date" in updates and updates["required_by_date"] != plan.required_by_date:
        if plan.source_type != INDEPENDENT:
            raise ValidationError(
                "A customer plan's required-by date is the Sales Order's.", fields={"required_by_date": "Not editable here."}
            )
        changes.append(f"required_by_date: {plan.required_by_date} -> {updates['required_by_date']}")
        plan.required_by_date = updates["required_by_date"]
    if "notes" in updates:
        notes = (updates["notes"] or "").strip() or None
        if notes != plan.notes:
            changes.append("notes changed")
            plan.notes = notes
    db.flush()
    return changes


def accept_plan(db: Session, plan: ProductionPlan) -> None:
    """draft -> planned. Needs a BOM basis (taken now from the active BOM if
    the plan had none) and, for customer plans, demand that still exists."""
    locked = db.query(ProductionPlan).filter(ProductionPlan.id == plan.id).with_for_update().one()
    if locked.status != PLAN_DRAFT:
        raise ConflictError(f"Only a draft plan can be accepted (this one is {locked.status}).")
    if locked.source_type == CUSTOMER_DEMAND and locked.requirement is not None and locked.requirement.status not in REQUIREMENT_ACTIVE:
        raise ConflictError(f"Its customer demand is {locked.requirement.status}; plan independent production instead.")
    if locked.bom_id is None:
        _snapshot_from_bom(db, locked)
    if locked.bom_id is None:
        raise ConflictError("BOM required: the product has no active BOM, so its raw-material needs are unknown.")
    locked.status = PLAN_PLANNED
    locked.planned_at = datetime.utcnow()
    db.flush()


def cancel_plan(db: Session, plan: ProductionPlan, reason: str) -> str:
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError("Say why the plan is cancelled.", fields={"reason": "Required."})
    locked = db.query(ProductionPlan).filter(ProductionPlan.id == plan.id).with_for_update().one()
    if locked.status == PLAN_CANCELLED:
        raise ConflictError("This plan is already cancelled.")
    previous = locked.status
    locked.status = PLAN_CANCELLED
    locked.cancelled_at = datetime.utcnow()
    locked.cancellation_reason = reason
    db.flush()
    return previous


# --- MRP read model ---------------------------------------------------------------


@dataclass
class MaterialNeed:
    raw_material_id: int
    raw_material_name: str
    unit_of_measure_id: int
    unit_code: str | None
    required_quantity: Decimal
    on_hand_quantity: Decimal
    committed_quantity: Decimal
    available_quantity: Decimal
    shortage_quantity: Decimal
    unit_mismatch: bool = False


@dataclass
class MrpRow:
    demand_type: str
    product_id: int
    product_name: str
    unit_of_measure_id: int
    production_requirement_id: int | None = None
    requirement_status: str | None = None
    sales_order_id: int | None = None
    sales_order_number: str | None = None
    line_number: int | None = None
    required_by_date: date | None = None
    required_quantity: Decimal | None = None  # ordered - delivered
    allocated_quantity: Decimal | None = None  # the line's FG claim
    outstanding_quantity: Decimal = _ZERO  # uncovered demand still requiring production
    fg_on_hand: Decimal = _ZERO
    fg_allocated: Decimal = _ZERO
    fg_free: Decimal = _ZERO
    planned_quantity: Decimal = _ZERO  # active plans (draft + planned)
    proposed_quantity: Decimal = _ZERO  # outstanding not yet planned
    excess_quantity: Decimal = _ZERO  # planned beyond the demand: free production
    plan_ids: list[int] = field(default_factory=list)
    plan_status: str = "unplanned"
    bom_status: str = "bom_required"
    bom_id: int | None = None
    materials: list[MaterialNeed] = field(default_factory=list)
    exceptions: list[str] = field(default_factory=list)


def _materials(db: Session, organisation_id: int, base: Decimal, components, quantity: Decimal, units: dict) -> list[MaterialNeed]:
    needs = []
    for component in components:
        material = db.get(RawMaterial, component.raw_material_id)
        on_hand = inventory_service.get_organisation_quantity_on_hand(db, organisation_id=organisation_id, raw_material_id=material.id)
        # The snapshot's unit must still be the material's stock unit; if
        # not, nothing is converted and the need is not stated.
        mismatch = material.unit_of_measure_id != component.unit_of_measure_id
        required = _ZERO if mismatch else bom_service.required_quantity(component.quantity, quantity, base)
        needs.append(
            MaterialNeed(
                raw_material_id=material.id,
                raw_material_name=material.name,
                unit_of_measure_id=component.unit_of_measure_id,
                unit_code=units.get(component.unit_of_measure_id),
                required_quantity=required,
                on_hand_quantity=on_hand,
                committed_quantity=_ZERO,
                available_quantity=on_hand,
                shortage_quantity=_ZERO if mismatch else max(required - on_hand, _ZERO),
                unit_mismatch=mismatch,
            )
        )
    return needs


def _plan_status(plans: list[ProductionPlan], outstanding: Decimal) -> str:
    if not plans:
        return "unplanned"
    if any(p.status == PLAN_DRAFT for p in plans):
        return PLAN_DRAFT
    if sum((p.planned_quantity for p in plans), _ZERO) < outstanding:
        return "partially_planned"
    return PLAN_PLANNED


def _finish(db: Session, row: MrpRow, organisation_id: int, base, components, basis: Decimal, units: dict) -> None:
    row.fg_on_hand, row.fg_allocated, row.fg_free = fg_allocation_service.product_position(db, organisation_id, row.product_id)
    if base is None:
        row.bom_status = "bom_required"
        row.exceptions.append("bom_required")
    else:
        row.bom_status = "snapshot"
        if basis > _ZERO:
            row.materials = _materials(db, organisation_id, base, components, basis, units)
        if any(m.unit_mismatch for m in row.materials):
            row.exceptions.append("unit_mismatch")
        if any(m.shortage_quantity > _ZERO for m in row.materials):
            row.exceptions.append("material_shortage")


def mrp_rows(db: Session, organisation_id: int, delivered_of) -> tuple[list[MrpRow], list[MaterialNeed]]:
    """Every customer demand (active requirement, or any requirement that
    still has active plans) and every active independent plan, with the
    raw-material needs of what is to be produced (active plans plus the
    unplanned remainder) and a per-material summary across all of them.
    `delivered_of(line_id)` gives an order line's delivered quantity."""
    units = {u.id: u.code for u in db.query(UnitOfMeasure).filter(UnitOfMeasure.organisation_id == organisation_id)}
    products = {p.id: p for p in db.query(Product).filter(Product.organisation_id == organisation_id)}
    plans = (
        db.query(ProductionPlan)
        .filter(ProductionPlan.organisation_id == organisation_id, ProductionPlan.status.in_(PLAN_ACTIVE))
        .order_by(ProductionPlan.id)
        .all()
    )
    plans_by_requirement: dict[int, list[ProductionPlan]] = {}
    for plan in plans:
        if plan.production_requirement_id is not None:
            plans_by_requirement.setdefault(plan.production_requirement_id, []).append(plan)
    requirements = (
        db.query(ProductionRequirement)
        .filter(ProductionRequirement.organisation_id == organisation_id)
        .filter(
            ProductionRequirement.status.in_(REQUIREMENT_ACTIVE)
            | ProductionRequirement.id.in_(list(plans_by_requirement) or [0])
        )
        .order_by(ProductionRequirement.id)
        .all()
    )
    rows: list[MrpRow] = []
    for requirement in requirements:
        line = db.get(SalesOrderLine, requirement.sales_order_line_id)
        order = requirement.sales_order
        own_plans = plans_by_requirement.get(requirement.id, [])
        outstanding = requirement.quantity if requirement.status in REQUIREMENT_ACTIVE else _ZERO
        planned = sum((p.planned_quantity for p in own_plans), _ZERO)
        product = products[requirement.product_id]
        row = MrpRow(
            demand_type=CUSTOMER_DEMAND,
            product_id=product.id,
            product_name=product.name,
            unit_of_measure_id=requirement.unit_of_measure_id,
            production_requirement_id=requirement.id,
            requirement_status=requirement.status,
            sales_order_id=order.id if order else None,
            sales_order_number=order.order_number if order else None,
            line_number=line.line_number if line else None,
            required_by_date=requirement.required_by_date,
            required_quantity=(line.quantity - delivered_of(line.id)) if line else None,
            allocated_quantity=fg_allocation_service.line_allocation(db, requirement.sales_order_line_id),
            outstanding_quantity=outstanding,
            planned_quantity=planned,
            proposed_quantity=max(outstanding - planned, _ZERO),
            excess_quantity=max(planned - outstanding, _ZERO),
            plan_ids=[p.id for p in own_plans],
            plan_status=_plan_status(own_plans, outstanding),
            bom_id=requirement.bom_id,
        )
        if requirement.status not in REQUIREMENT_ACTIVE:
            row.exceptions.append(f"demand_{requirement.status}")
        basis = planned + row.proposed_quantity
        # The requirement's snapshot, else the first plan's own snapshot.
        source = requirement if requirement.bom_id is not None else next((p for p in own_plans if p.bom_id is not None), None)
        if source is not None:
            row.bom_id = source.bom_id
        _finish(db, row, organisation_id, source.bom_base_quantity if source else None, source.components if source else [], basis, units)
        rows.append(row)
    for plan in plans:
        if plan.source_type != INDEPENDENT:
            continue
        product = products[plan.product_id]
        row = MrpRow(
            demand_type=INDEPENDENT,
            product_id=product.id,
            product_name=product.name,
            unit_of_measure_id=plan.unit_of_measure_id,
            required_by_date=plan.required_by_date,
            planned_quantity=plan.planned_quantity,
            excess_quantity=plan.planned_quantity,
            plan_ids=[plan.id],
            plan_status=plan.status,
            bom_id=plan.bom_id,
        )
        if plan.bom_id is not None:
            _finish(db, row, organisation_id, plan.bom_base_quantity, plan.components, plan.planned_quantity, units)
        else:
            # A draft without a snapshot yet: preview the active BOM, if any
            # (a transient object, never added to the session).
            preview = ProductionPlan(organisation_id=organisation_id, product_id=plan.product_id)
            _snapshot_from_bom(db, preview)
            row.bom_id = preview.bom_id
            _finish(db, row, organisation_id, preview.bom_base_quantity, preview.components, plan.planned_quantity, units)
        rows.append(row)

    summary: dict[int, MaterialNeed] = {}
    for row in rows:
        for need in row.materials:
            if need.unit_mismatch:
                continue
            total = summary.get(need.raw_material_id)
            if total is None:
                summary[need.raw_material_id] = MaterialNeed(**{**need.__dict__})
            else:
                total.required_quantity += need.required_quantity
    for need in summary.values():
        need.shortage_quantity = max(need.required_quantity - need.available_quantity, _ZERO)
    return rows, sorted(summary.values(), key=lambda n: n.raw_material_name)
