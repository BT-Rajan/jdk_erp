"""Quotation readiness gate (Sales S9).

Answers "is this quotation commercially and operationally ready for the
next Sales decision?" -- a decision input only. It is NOT acceptance: it
accepts, rejects, expires or converts nothing, and reserves, produces,
buys, bills or delivers nothing.

Everything is read from the services that own it; nothing is
recalculated here:
- delivery window      -> working_calendar_service (S5)
- operational decision -> the quotation's current FeasibilityCheck (S8),
                          which itself used S6 (same day) or S7 (0-2 days)
- commercial pricing   -> the quotation lines' price flags (S4)

Operational rules:
- no requested delivery date              -> operational_assessment_required
- more_than_2_working_days                -> no feasibility needed
- not_servable (Fri/Sat/holiday date)     -> admin_override_required; the
                                             date is never changed
- same_day / within_2_working_days        -> needs a current S8 record:
    none                                  -> operational_assessment_required
    not current (inputs changed / newer)  -> operational_assessment_required
    for a different delivery window       -> operational_assessment_required
    calculated / approved                 -> satisfied
    admin_override_required               -> admin_override_required
    rejected                              -> not_servable

Commercial rule: any line needing price approval -> commercial approval
required. No approval mechanism exists yet, so nothing can clear it.

Status precedence when several conditions apply (all are reported in
`conditions` and `reason_codes`): not_servable, admin_override_required,
operational_assessment_required, commercial_approval_required, ready."""

import json
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.timezone import now_jdk
from app.models.feasibility_check import (
    ADMIN_OVERRIDE_REQUIRED as CHECK_OVERRIDE_REQUIRED,
    APPROVED,
    CALCULATED,
    REJECTED,
    FeasibilityCheck,
)
from app.models.quotation import Quotation
from app.services import feasibility_record_service, working_calendar_service

READY = "ready"
OPERATIONAL_ASSESSMENT_REQUIRED = "operational_assessment_required"
ADMIN_OVERRIDE_REQUIRED = "admin_override_required"
COMMERCIAL_APPROVAL_REQUIRED = "commercial_approval_required"
NOT_SERVABLE = "not_servable"
_PRECEDENCE = (NOT_SERVABLE, ADMIN_OVERRIDE_REQUIRED, OPERATIONAL_ASSESSMENT_REQUIRED, COMMERCIAL_APPROVAL_REQUIRED)

REQUESTED_DATE_MISSING = "requested_date_missing"
REQUESTED_DATE_NON_WORKING = "requested_date_non_working"
FEASIBILITY_REQUIRED = "feasibility_required"
FEASIBILITY_STALE = "feasibility_stale"
FEASIBILITY_REJECTED = "feasibility_rejected"
PRICE_OUTSIDE_RANGE = "price_outside_range"
PRICE_RANGE_NOT_SET = "price_range_not_set"

_WINDOWS_NEEDING_FEASIBILITY = (working_calendar_service.SAME_DAY, working_calendar_service.WITHIN_2_WORKING_DAYS)


@dataclass
class Readiness:
    status: str
    delivery_window: str | None
    conditions: list[str] = field(default_factory=list)
    reason_codes: list[str] = field(default_factory=list)
    feasibility_check_id: int | None = None
    feasibility_state: str | None = None
    commercial_approval_required: bool = False


def _operational(db: Session, quotation: Quotation, window: str | None, readiness: Readiness) -> None:
    def block(condition: str, *codes: str) -> None:
        readiness.conditions.append(condition)
        readiness.reason_codes.extend(codes)

    if window is None:
        block(OPERATIONAL_ASSESSMENT_REQUIRED, REQUESTED_DATE_MISSING)
        return
    if window == working_calendar_service.NOT_SERVABLE:
        block(ADMIN_OVERRIDE_REQUIRED, REQUESTED_DATE_NON_WORKING)
        return
    if window not in _WINDOWS_NEEDING_FEASIBILITY:
        return

    record: FeasibilityCheck | None = feasibility_record_service.latest_for_quotation(db, quotation.id)
    if record is None:
        block(OPERATIONAL_ASSESSMENT_REQUIRED, FEASIBILITY_REQUIRED)
        return
    readiness.feasibility_check_id = record.id
    readiness.feasibility_state = record.state
    if not feasibility_record_service.is_current(db, record, quotation) or record.delivery_window != window:
        block(OPERATIONAL_ASSESSMENT_REQUIRED, FEASIBILITY_STALE)
    elif record.state == CHECK_OVERRIDE_REQUIRED:
        block(ADMIN_OVERRIDE_REQUIRED, *json.loads(record.reason_codes))
    elif record.state == REJECTED:
        block(NOT_SERVABLE, FEASIBILITY_REJECTED)
    elif record.state not in (CALCULATED, APPROVED):
        # A record whose own calendar answer was not_servable while the
        # window is now same/within-2 can only mean the inputs moved on.
        block(OPERATIONAL_ASSESSMENT_REQUIRED, FEASIBILITY_STALE)


def _commercial(quotation: Quotation, readiness: Readiness) -> None:
    codes = []
    for line in quotation.lines:
        if not line.price_approval_required:
            continue
        codes.append(PRICE_RANGE_NOT_SET if line.min_selling_price is None or line.max_selling_price is None else PRICE_OUTSIDE_RANGE)
    if codes:
        readiness.commercial_approval_required = True
        readiness.conditions.append(COMMERCIAL_APPROVAL_REQUIRED)
        readiness.reason_codes.extend(sorted(set(codes)))


def assess(db: Session, quotation: Quotation, now: datetime | None = None) -> Readiness:
    """Read-only: computes readiness from current server data (Kuwait
    time). Changes nothing."""
    window = None
    if quotation.requested_delivery_date is not None:
        window = working_calendar_service.classify_delivery_window(
            db, quotation.organisation_id, quotation.requested_delivery_date, now=now or now_jdk()
        )
    readiness = Readiness(status=READY, delivery_window=window)
    _operational(db, quotation, window, readiness)
    _commercial(quotation, readiness)
    for status in _PRECEDENCE:
        if status in readiness.conditions:
            readiness.status = status
            break
    return readiness
