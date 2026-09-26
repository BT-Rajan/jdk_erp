"""Feasibility decision records and their lifecycle (Sales S8).

Lifecycle only -- the calculations themselves live elsewhere and are
called, never copied:
- same_day              -> same_day_fg_service.check_same_day_fg_availability (S6)
- within_2_working_days -> feasibility_service.calculate (S7)
- more_than_2_working_days -> no check required (business rule)
- not_servable          -> result not_servable, waiting for an Admin
                           decision like any other exception

Each run stores a new FeasibilityCheck; earlier ones are never rewritten.
A record is authoritative only while it is the quotation's latest record
AND its snapshotted inputs still match the quotation (is_current). There
is no validity period and no automatic re-check. Nothing here reserves
or moves stock, creates production or orders, or changes the quotation."""

import json
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.errors import ConflictError
from app.core.timezone import now_jdk
from app.models.feasibility_check import (
    ADMIN_OVERRIDE_REQUIRED,
    APPROVED,
    CALCULATED,
    DECIDABLE_STATES,
    REJECTED,
    FeasibilityCheck,
    FeasibilityCheckLine,
)
from app.models.quotation import Quotation
from app.services import feasibility_service, same_day_fg_service, working_calendar_service
from app.services.same_day_fg_service import RequestedQuantity

SAME_DAY_BASIS = "same_day_fg/v1"
WITHIN_2_BASIS = "within_2_feasibility/v1"
CALENDAR_BASIS = "working_calendar/v1"

NO_CHECK_REQUIRED = "no_check_required"
# Same code the readiness gate reports for this condition.
NON_WORKING_REQUESTED_DATE = "requested_date_non_working"

DECISION_STATES = {"approved": APPROVED, "rejected": REJECTED}


def _requested(quotation: Quotation) -> list[RequestedQuantity]:
    return [RequestedQuantity(line.product_id, line.quantity, line.unit_of_measure_id) for line in quotation.lines]


def _inputs(customer_id, requested_delivery_date, lines) -> tuple:
    """The feasibility-relevant inputs, in a comparable form."""
    return (
        customer_id,
        requested_delivery_date,
        sorted((line.product_id, _quantity_key(line.quantity), line.unit_of_measure_id) for line in lines),
    )


def _quantity_key(value) -> str:
    """2 and 2.0000 compare equal."""
    return format(Decimal(value).normalize(), "f")


def run_check(db: Session, quotation: Quotation, user_id: int, now: datetime | None = None) -> FeasibilityCheck:
    """Calculates feasibility for the quotation as it is now and stores the
    result as a new record. Used both for the first check and for every
    re-check. The caller commits."""
    if quotation.requested_delivery_date is None:
        raise ConflictError("This quotation has no requested delivery date to check.")
    current = now or now_jdk()
    requested = _requested(quotation)
    window = working_calendar_service.classify_delivery_window(
        db, quotation.organisation_id, quotation.requested_delivery_date, now=current
    )

    failed_stage = None
    stages: list = []
    if window == working_calendar_service.SAME_DAY:
        basis = SAME_DAY_BASIS
        availability = same_day_fg_service.check_same_day_fg_availability(db, quotation.organisation_id, requested)
        result = availability.decision
        reason_codes = ["fg_sufficient"] if result == same_day_fg_service.SERVABLE else ["fg_insufficient"]
        failed_stage = None if result == same_day_fg_service.SERVABLE else feasibility_service.FINISHED_GOODS
        stages = [
            {"product_id": s.product_id, "requested": str(s.requested), "available": str(s.available)}
            for s in availability.shortages
        ]
    elif window == working_calendar_service.WITHIN_2_WORKING_DAYS:
        basis = WITHIN_2_BASIS
        calculation = feasibility_service.calculate(
            db, quotation.organisation_id, quotation.requested_delivery_date, requested, now=current
        )
        result, failed_stage, reason_codes = calculation.decision, calculation.failed_stage, calculation.reason_codes
        stages = [asdict(stage) for stage in calculation.stages]
    elif window == working_calendar_service.MORE_THAN_2_WORKING_DAYS:
        basis, result, reason_codes = CALENDAR_BASIS, same_day_fg_service.SERVABLE, [NO_CHECK_REQUIRED]
    else:
        basis, result, reason_codes = CALENDAR_BASIS, same_day_fg_service.NOT_SERVABLE, [NON_WORKING_REQUESTED_DATE]

    # A non-working requested date is not servable as calculated, but the
    # business rule sends it to Admin (S0.2): it waits for the same S8
    # decision as any other exception. The calculated result is kept.
    if result in (same_day_fg_service.ADMIN_OVERRIDE_REQUIRED, same_day_fg_service.NOT_SERVABLE):
        state = ADMIN_OVERRIDE_REQUIRED
    else:
        state = CALCULATED

    record = FeasibilityCheck(
        organisation_id=quotation.organisation_id,
        quotation_id=quotation.id,
        customer_id=quotation.customer_id,
        requested_delivery_date=quotation.requested_delivery_date,
        delivery_window=window,
        calculation_basis=basis,
        calculated_at=current.astimezone(UTC).replace(tzinfo=None),  # stored naive UTC, like every timestamp
        result=result,
        failed_stage=failed_stage,
        reason_codes=json.dumps(reason_codes),
        stages=json.dumps(stages),
        state=state,
        created_by_user_id=user_id,
    )
    record.lines = [
        FeasibilityCheckLine(product_id=item.product_id, quantity=item.quantity, unit_of_measure_id=item.unit_of_measure_id)
        for item in requested
    ]
    db.add(record)
    db.flush()
    return record


def latest_for_quotation(db: Session, quotation_id: int) -> FeasibilityCheck | None:
    return (
        db.query(FeasibilityCheck)
        .filter(FeasibilityCheck.quotation_id == quotation_id)
        .order_by(FeasibilityCheck.id.desc())
        .first()
    )


def is_current(db: Session, record: FeasibilityCheck, quotation: Quotation) -> bool:
    """Authoritative only while it is the quotation's latest record and the
    quotation's feasibility inputs (customer, requested date, products,
    quantities, units) still match what was calculated. Anything else needs a fresh
    check -- an old result is never silently reused."""
    latest = latest_for_quotation(db, quotation.id)
    if latest is None or latest.id != record.id:
        return False
    return _inputs(record.customer_id, record.requested_delivery_date, record.lines) == _inputs(
        quotation.customer_id, quotation.requested_delivery_date, quotation.lines
    )


def decide(db: Session, record: FeasibilityCheck, quotation: Quotation, decision: str, reason: str, user_id: int) -> str:
    """Admin's decision on an exception. Only for a record that needed one
    and is still current. Returns the previous state; the caller audits
    and commits. The calculated result is left exactly as it was."""
    if record.state not in DECIDABLE_STATES:
        raise ConflictError("This feasibility result does not need an Admin decision.")
    if not is_current(db, record, quotation):
        raise ConflictError("This feasibility result is no longer current -- run a fresh check first.")
    previous = record.state
    record.state = DECISION_STATES[decision]
    record.decision_reason = reason
    record.decided_by_user_id = user_id
    record.decided_at = datetime.utcnow()
    db.add(record)
    return previous
