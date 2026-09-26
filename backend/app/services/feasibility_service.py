"""0-2 working-day feasibility calculation (Sales S7) -- calculation only.

Answers "can this requested delivery currently be fulfilled?" for a
request whose delivery window is within_2_working_days. It records
nothing and changes nothing: no reservation, stock movement, production
or order. Storing results and Admin decisions is S8.

Stages run in this fixed order and stop at the first failure (a failed
stage never lets a later one report the request as feasible):

1. finished_goods   -- FG on hand covers every product -> servable.
                        Otherwise the per-product shortfall moves on.
2. raw_materials    -- each short product's shortfall exploded through
                        its active BOM; summed material needs compared
                        to raw-material stock on hand. No active BOM
                        fails.
3. production_time  -- each short product's manufacturing lead time
                        (days) must be <= the working days available
                        until the requested date. No lead time fails.
4. manpower         -- staff required by the short products (summed)
                        must be <= the organisation's production staff
                        available per day. Either figure unset fails.
5. machine          -- every product is currently made on the one
                        machine, which is always available (business
                        decision): passes, and says so.

Any failure -> admin_override_required. All stock figures come from the
authoritative snapshots via finished_goods_inventory_service and
inventory_service; quantities are compared in each item's own stock
unit and never converted."""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleError
from app.core.timezone import now_jdk, to_jdk_time
from app.models.bom import ACTIVE, Bom, BomComponent
from app.models.organisation import Organisation
from app.models.product import Product
from app.services import bom_service, finished_goods_inventory_service, inventory_service, working_calendar_service
from app.services.same_day_fg_service import ADMIN_OVERRIDE_REQUIRED, SERVABLE, RequestedQuantity

FINISHED_GOODS = "finished_goods"
RAW_MATERIALS = "raw_materials"
PRODUCTION_TIME = "production_time"
MANPOWER = "manpower"
MACHINE = "machine"
STAGES = (FINISHED_GOODS, RAW_MATERIALS, PRODUCTION_TIME, MANPOWER, MACHINE)

PASSED = "passed"
FAILED = "failed"
# Finished goods only: stock doesn't cover the request, so production is
# checked next. Not itself a failure.
SHORTFALL = "shortfall"
NOT_REACHED = "not_reached"

# Structured reason codes.
FG_SUFFICIENT = "fg_sufficient"
BOM_MISSING = "bom_missing"
RAW_MATERIAL_SHORTAGE = "raw_material_shortage"
LEAD_TIME_NOT_SET = "lead_time_not_set"
LEAD_TIME_EXCEEDS_WINDOW = "lead_time_exceeds_window"
MANPOWER_NOT_CONFIGURED = "manpower_not_configured"
MANPOWER_INSUFFICIENT = "manpower_insufficient"
MACHINE_ASSUMED_AVAILABLE = "machine_assumed_available"


@dataclass
class StageResult:
    stage: str
    status: str
    reason_codes: list[str] = field(default_factory=list)
    details: list[str] = field(default_factory=list)


@dataclass
class FeasibilityCalculation:
    """`applies` is False when the request isn't within 2 working days;
    everything else is then empty."""

    delivery_window: str | None
    applies: bool
    decision: str | None = None
    failed_stage: str | None = None
    reason_codes: list[str] = field(default_factory=list)
    working_days_available: int | None = None
    stages: list[StageResult] = field(default_factory=list)


def _requested_totals(db: Session, organisation_id: int, requested: list[RequestedQuantity]) -> dict[int, tuple[Product, Decimal]]:
    totals: dict[int, tuple[Product, Decimal]] = {}
    for item in requested:
        product = db.query(Product).filter(Product.id == item.product_id, Product.organisation_id == organisation_id).first()
        if product is None:
            raise BusinessRuleError("A requested product no longer exists.")
        if item.unit_of_measure_id != product.unit_of_measure_id:
            raise BusinessRuleError(
                f"{product.name} is requested in a different unit from its stock unit; "
                "feasibility cannot be calculated without a conversion."
            )
        previous = totals.get(product.id, (product, Decimal("0")))[1]
        totals[product.id] = (product, previous + item.quantity)
    return totals


def _finished_goods(db, organisation_id, totals) -> tuple[StageResult, dict[int, tuple[Product, Decimal]]]:
    shortfalls = {}
    details = []
    for product_id, (product, quantity) in totals.items():
        available = finished_goods_inventory_service.get_organisation_quantity_on_hand(
            db, organisation_id=organisation_id, product_id=product_id
        )
        if available < quantity:
            shortfalls[product_id] = (product, quantity - available)
            details.append(f"{product.name}: requested {quantity}, FG available {available}, to produce {quantity - available}")
    if not shortfalls:
        return StageResult(FINISHED_GOODS, PASSED, [FG_SUFFICIENT]), shortfalls
    return StageResult(FINISHED_GOODS, SHORTFALL, [], details), shortfalls


def _raw_materials(db, organisation_id, shortfalls) -> StageResult:
    reasons, details = [], []
    needs: dict[int, Decimal] = {}
    for product, quantity in shortfalls.values():
        bom = (
            db.query(Bom)
            .filter(Bom.organisation_id == organisation_id, Bom.product_id == product.id, Bom.status == ACTIVE)
            .first()
        )
        if bom is None:
            reasons.append(BOM_MISSING)
            details.append(f"{product.name}: no active BOM")
            continue
        for component in db.query(BomComponent).filter(BomComponent.bom_id == bom.id).all():
            required = bom_service.required_quantity(component.quantity, quantity, bom.base_quantity)
            needs[component.raw_material_id] = needs.get(component.raw_material_id, Decimal("0")) + required
    for raw_material_id, required in needs.items():
        available = inventory_service.get_organisation_quantity_on_hand(
            db, organisation_id=organisation_id, raw_material_id=raw_material_id
        )
        if available < required:
            reasons.append(RAW_MATERIAL_SHORTAGE)
            details.append(f"raw material {raw_material_id}: required {required}, available {available}")
    if reasons:
        return StageResult(RAW_MATERIALS, FAILED, sorted(set(reasons)), details)
    return StageResult(RAW_MATERIALS, PASSED)


def _production_time(shortfalls, working_days_available: int) -> StageResult:
    reasons, details = [], []
    for product, _ in shortfalls.values():
        lead_time = product.manufacturing_lead_time_days
        if lead_time is None:
            reasons.append(LEAD_TIME_NOT_SET)
            details.append(f"{product.name}: no manufacturing lead time set")
        elif lead_time > working_days_available:
            reasons.append(LEAD_TIME_EXCEEDS_WINDOW)
            details.append(f"{product.name}: lead time {lead_time} day(s) > {working_days_available} working day(s) available")
    if reasons:
        return StageResult(PRODUCTION_TIME, FAILED, sorted(set(reasons)), details)
    return StageResult(PRODUCTION_TIME, PASSED)


def _manpower(db, organisation_id, shortfalls) -> StageResult:
    available = (
        db.query(Organisation.production_staff_available_per_day).filter(Organisation.id == organisation_id).scalar()
    )
    missing = [product.name for product, _ in shortfalls.values() if product.production_staff_required is None]
    if available is None or missing:
        details = []
        if available is None:
            details.append("production staff available per day is not set")
        details += [f"{name}: production staff required is not set" for name in missing]
        return StageResult(MANPOWER, FAILED, [MANPOWER_NOT_CONFIGURED], details)
    required = sum(product.production_staff_required for product, _ in shortfalls.values())
    if required > available:
        return StageResult(MANPOWER, FAILED, [MANPOWER_INSUFFICIENT], [f"staff required {required} > available {available}"])
    return StageResult(MANPOWER, PASSED)


def calculate(
    db: Session,
    organisation_id: int,
    requested_delivery_date: date,
    requested: list[RequestedQuantity],
    now: datetime | None = None,
) -> FeasibilityCalculation:
    current = to_jdk_time(now) if now is not None else now_jdk()
    window = working_calendar_service.classify_delivery_window(db, organisation_id, requested_delivery_date, now=current)
    if window != working_calendar_service.WITHIN_2_WORKING_DAYS:
        return FeasibilityCalculation(delivery_window=window, applies=False)

    start = working_calendar_service.applicable_working_day(db, organisation_id, current)
    working_days_available = working_calendar_service.working_days_until(db, organisation_id, start, requested_delivery_date)
    result = FeasibilityCalculation(delivery_window=window, applies=True, working_days_available=working_days_available)

    totals = _requested_totals(db, organisation_id, requested)
    fg_stage, shortfalls = _finished_goods(db, organisation_id, totals)
    result.stages.append(fg_stage)
    if fg_stage.status == PASSED:
        return _finish(result, SERVABLE)

    checks = (
        lambda: _raw_materials(db, organisation_id, shortfalls),
        lambda: _production_time(shortfalls, working_days_available),
        lambda: _manpower(db, organisation_id, shortfalls),
        lambda: StageResult(MACHINE, PASSED, [MACHINE_ASSUMED_AVAILABLE], ["single machine, assumed always available"]),
    )
    for check in checks:
        stage = check()
        result.stages.append(stage)
        if stage.status == FAILED:
            result.failed_stage = stage.stage
            result.reason_codes = list(stage.reason_codes)
            return _finish(result, ADMIN_OVERRIDE_REQUIRED)
    result.reason_codes = [MACHINE_ASSUMED_AVAILABLE]
    return _finish(result, SERVABLE)


def _finish(result: FeasibilityCalculation, decision: str) -> FeasibilityCalculation:
    reached = {stage.stage for stage in result.stages}
    result.stages += [StageResult(stage, NOT_REACHED) for stage in STAGES if stage not in reached]
    if decision == SERVABLE and not result.reason_codes:
        result.reason_codes = [FG_SUFFICIENT]
    result.decision = decision
    return result
