"""Same-day Finished Goods availability gate (Sales S6).

Same day means Finished Goods availability only: no raw materials, BOM,
production time, machines, manpower or scheduling are looked at. The
check reads the authoritative FG snapshot through
finished_goods_inventory_service and never writes anything -- no
reservation, no stock movement, no snapshot change.

Decisions:
- every requested product has enough FG on hand -> servable
- any product is short -> admin_override_required, until Admin decides.
  The only Admin decision is the one on the quotation's current S8
  feasibility record (feasibility_record_service): approved -> servable,
  rejected -> not_servable. This service stores no decision of its own.

The gate applies only when the quotation's requested delivery date
classifies as same_day right now (working_calendar_service); any other
classification means this gate does not apply."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleError
from app.models.product import Product
from app.models.quotation import Quotation
from app.services import finished_goods_inventory_service, working_calendar_service

SERVABLE = "servable"
ADMIN_OVERRIDE_REQUIRED = "admin_override_required"
NOT_SERVABLE = "not_servable"


@dataclass(frozen=True)
class RequestedQuantity:
    product_id: int
    quantity: Decimal
    unit_of_measure_id: int


@dataclass
class Shortage:
    product_id: int
    requested: Decimal
    available: Decimal


@dataclass
class FgAvailability:
    """`decision` is SERVABLE or ADMIN_OVERRIDE_REQUIRED -- the raw stock
    answer, before any Admin decision is applied."""

    decision: str
    shortages: list[Shortage] = field(default_factory=list)


def check_same_day_fg_availability(
    db: Session, organisation_id: int, requested: list[RequestedQuantity]
) -> FgAvailability:
    """All-or-nothing across every requested line; the same product on
    several lines is summed before comparing. Quantities must be in the
    product's own stock unit -- the unit FG is held in -- and are never
    converted: a different unit (e.g. the product's unit changed after
    the quotation) is refused rather than compared."""
    totals: dict[int, Decimal] = {}
    for item in requested:
        product = db.query(Product).filter(Product.id == item.product_id, Product.organisation_id == organisation_id).first()
        if product is None:
            raise BusinessRuleError("A requested product no longer exists.")
        if item.unit_of_measure_id != product.unit_of_measure_id:
            raise BusinessRuleError(
                f"{product.name} is requested in a different unit from its stock unit; "
                "Finished Goods availability cannot be compared without a conversion."
            )
        totals[item.product_id] = totals.get(item.product_id, Decimal("0")) + item.quantity

    shortages = []
    for product_id, quantity in totals.items():
        available = finished_goods_inventory_service.get_organisation_quantity_on_hand(
            db, organisation_id=organisation_id, product_id=product_id
        )
        if available < quantity:
            shortages.append(Shortage(product_id=product_id, requested=quantity, available=available))
    return FgAvailability(decision=ADMIN_OVERRIDE_REQUIRED if shortages else SERVABLE, shortages=shortages)


@dataclass
class SameDayGate:
    """`applies` is False when the requested date is missing or doesn't
    classify as same_day now; `decision` is then None."""

    delivery_window: str | None
    applies: bool
    decision: str | None = None
    shortages: list[Shortage] = field(default_factory=list)


def evaluate_quotation(db: Session, quotation: Quotation, now: datetime | None = None) -> SameDayGate:
    if quotation.requested_delivery_date is None:
        return SameDayGate(delivery_window=None, applies=False)
    window = working_calendar_service.classify_delivery_window(
        db, quotation.organisation_id, quotation.requested_delivery_date, now=now
    )
    if window != working_calendar_service.SAME_DAY:
        return SameDayGate(delivery_window=window, applies=False)

    availability = check_same_day_fg_availability(
        db,
        quotation.organisation_id,
        [RequestedQuantity(line.product_id, line.quantity, line.unit_of_measure_id) for line in quotation.lines],
    )
    decision = availability.decision
    if decision == ADMIN_OVERRIDE_REQUIRED:
        # Local import: feasibility_record_service imports this module.
        from app.models.feasibility_check import APPROVED, REJECTED
        from app.services import feasibility_record_service

        record = feasibility_record_service.latest_for_quotation(db, quotation.id)
        if record is not None and feasibility_record_service.is_current(db, record, quotation, now):
            if record.state == APPROVED:
                decision = SERVABLE
            elif record.state == REJECTED:
                decision = NOT_SERVABLE
    return SameDayGate(delivery_window=window, applies=True, decision=decision, shortages=availability.shortages)
