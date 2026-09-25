"""RFQ business logic that doesn't belong inline in the API layer --
numbering, status-transition rules, response capture, decision recording,
and conversion into a Purchase Order (docs/modules/rfq.md). Mirrors
app/services/purchase_order_service.py's shape. Never commits -- the
caller commits alongside whatever audit_service.log_event call belongs
with the same change."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleError, ConflictError, ValidationError
from app.models.purchase_order import PurchaseOrder, PurchaseOrderLine
from app.models.raw_material import RawMaterial
from app.models.unit import UnitOfMeasure
from app.models.rfq import (
    ALLOWED_STATUS_TRANSITIONS,
    CONVERTED,
    INVITATION_DECLINED,
    INVITATION_QUOTED,
    INVITATION_SENT,
    ISSUED,
    RESPONSE_RECEIVED,
    SELECTED,
    Rfq,
    RfqInvitationFollowUp,
    RfqLine,
    RfqResponse,
    RfqResponseLine,
    RfqSupplierInvitation,
)
from app.services import purchase_order_service, uom_conversion

_MAX_YEARLY_SEQUENCE = 9999


def generate_rfq_number(db: Session, organisation_id: int, today: date | None = None) -> str:
    """`YY3NNNN` -- 2-digit year, fixed RFQ-type digit `3`, 4-digit
    sequence that resets every calendar year (docs/modules/rfq.md #10).
    Counts existing RFQs for this organisation whose number already
    starts with this year's `YY3` prefix -- the same count-and-retry
    discipline every other code generator in this codebase uses, just
    scoped by year (docs/audit/RFQ_AUDIT.md #2)."""
    today = today or date.today()
    prefix = f"{today.year % 100:02d}3"
    existing = db.query(Rfq).filter(Rfq.organisation_id == organisation_id, Rfq.rfq_number.like(f"{prefix}%")).count()
    sequence = existing + 1
    if sequence > _MAX_YEARLY_SEQUENCE:
        raise ConflictError("This organisation has reached the maximum number of RFQs for this year.")
    return f"{prefix}{sequence:04d}"


def assert_transition_allowed(current_status: str, target_status: str) -> None:
    allowed = ALLOWED_STATUS_TRANSITIONS.get(current_status, set())
    if target_status not in allowed:
        raise BusinessRuleError(f"Cannot change RFQ status from '{current_status}' to '{target_status}'.")


def line_unit_ratio(
    unit: UnitOfMeasure, material: RawMaterial, material_alternate_unit: UnitOfMeasure | None, material_unit: UnitOfMeasure
) -> Decimal | None:
    """`1 [unit] = ratio [material's own unit]`, or None when no valid
    conversion exists (app/services/uom_conversion.py). An RFQ line is
    only accepted in a unit with a ratio, so its PO line -- always in the
    material's own unit (docs/modules/purchase_orders.md #5) -- can
    always be derived."""
    return uom_conversion.resolve_conversion_ratio(unit, material_unit, material, material_alternate_unit)


def _resolve_quoted_unit(db: Session, *, unit_id: int, raw_material_id: int, organisation_id: int) -> None:
    """Validates a supplier-quoted unit that differs from its RFQ line's
    own unit: must be an active unit in this organisation, and must
    convert to the material's own unit -- the same discipline
    app/api/rfqs.py's _validate_form already applies to an RFQ line's own
    unit_of_measure_id (gap-fix: supplier UOM mismatch, e.g. RFQ in KG,
    supplier quotes per TON)."""
    material = (
        db.query(RawMaterial)
        .filter(
            RawMaterial.id == raw_material_id,
            RawMaterial.organisation_id == organisation_id,
            RawMaterial.is_active.is_(True),
        )
        .first()
    )
    if material is None:
        raise BusinessRuleError("This RFQ line's material is no longer active.")
    unit_ids = [unit_id, material.unit_of_measure_id]
    if material.alternate_conversion_unit_of_measure_id:
        unit_ids.append(material.alternate_conversion_unit_of_measure_id)
    units = {
        u.id: u
        for u in db.query(UnitOfMeasure).filter(
            UnitOfMeasure.id.in_(unit_ids), UnitOfMeasure.organisation_id == organisation_id
        )
    }
    unit = units.get(unit_id)
    if unit is None or not unit.is_active:
        raise ValidationError(
            "The quoted unit must be an active unit in your organisation.",
            fields={"lines": "Invalid quoted unit of measure."},
        )
    material_unit = units[material.unit_of_measure_id]
    alternate = (
        units.get(material.alternate_conversion_unit_of_measure_id)
        if material.alternate_conversion_unit_of_measure_id
        else None
    )
    if line_unit_ratio(unit, material, alternate, material_unit) is None:
        raise ValidationError(
            f"{material.name}: the quoted unit {unit.code} does not convert to its unit {material_unit.code}.",
            fields={"lines": "Quoted unit has no conversion to the material's unit."},
        )


@dataclass
class ResponseLineInput:
    rfq_line_id: int
    unit_price: Decimal
    # None -> quoted at the RFQ line's own requested quantity (gap-fix:
    # partial quotation).
    quantity: Decimal | None
    # None -> quoted in the RFQ line's own requested unit (gap-fix:
    # supplier UOM mismatch).
    unit_of_measure_id: int | None
    delivery_days: int | None
    remarks: str | None


def capture_response(
    db: Session,
    *,
    rfq: Rfq,
    invitation: RfqSupplierInvitation,
    response_received_at: datetime,
    supplier_quotation_number: str | None,
    quotation_date: date | None,
    valid_until: date | None,
    payment_terms: str | None,
    delivery_terms: str | None,
    freight_terms: str | None,
    note: str | None,
    lines: list[ResponseLineInput],
    created_by_user_id: int | None,
) -> RfqResponse:
    """docs/modules/rfq.md #5. Only valid once an RFQ has been issued and
    before a decision. `invitation` must already have been resolved
    against this RFQ by the caller. Every quoted line must reference a
    real line on this RFQ -- a line id from another RFQ (including one in
    another organisation) is rejected, never silently dropped.

    Side effects, never direct targets: the invitation becomes `quoted`
    (also from `declined` -- a supplier who said no and later quoted
    anyway is a real quote), and the RFQ's first captured response across
    any invitation moves it `issued -> response_received`. A later
    response on the same invitation is a revision: a new row, the earlier
    one untouched (#12)."""
    if invitation.rfq_id != rfq.id:
        raise BusinessRuleError("This invitation does not belong to this RFQ.")
    if rfq.status not in (ISSUED, RESPONSE_RECEIVED):
        raise BusinessRuleError("Can only capture a supplier response for an issued RFQ.")

    requested_ids = {line.rfq_line_id for line in lines}
    rfq_lines_by_id = {
        row.id: row
        for row in db.query(RfqLine).filter(RfqLine.rfq_id == rfq.id, RfqLine.id.in_(requested_ids)).all()
    }
    if set(rfq_lines_by_id) != requested_ids:
        raise ValidationError(
            "One or more quoted lines do not belong to this RFQ.",
            fields={"lines": "Every quoted line must be a line on this RFQ."},
        )

    for line in lines:
        if line.unit_of_measure_id is None:
            continue
        rfq_line = rfq_lines_by_id[line.rfq_line_id]
        if line.unit_of_measure_id == rfq_line.unit_of_measure_id:
            continue
        _resolve_quoted_unit(db, unit_id=line.unit_of_measure_id, raw_material_id=rfq_line.raw_material_id, organisation_id=rfq.organisation_id)

    response = RfqResponse(
        organisation_id=rfq.organisation_id,
        invitation_id=invitation.id,
        response_received_at=response_received_at,
        supplier_quotation_number=supplier_quotation_number,
        quotation_date=quotation_date,
        valid_until=valid_until,
        payment_terms=payment_terms,
        delivery_terms=delivery_terms,
        freight_terms=freight_terms,
        note=note,
        created_by_user_id=created_by_user_id,
    )
    db.add(response)
    db.flush()
    db.add_all(
        RfqResponseLine(
            response_id=response.id,
            rfq_line_id=line.rfq_line_id,
            unit_price=line.unit_price,
            quantity=line.quantity,
            unit_of_measure_id=line.unit_of_measure_id,
            delivery_days=line.delivery_days,
            remarks=line.remarks,
        )
        for line in lines
    )

    if invitation.status != INVITATION_QUOTED:
        invitation.status = INVITATION_QUOTED
        db.add(invitation)
    if rfq.status == ISSUED:
        rfq.status = RESPONSE_RECEIVED
        db.add(rfq)
    db.flush()
    return response


def decline_invitation(rfq: Rfq, invitation: RfqSupplierInvitation) -> None:
    """docs/modules/rfq.md #4 -- a flag only: no effect on the RFQ's
    status, on other invitations, or on any captured response. Only a
    still-`sent` invitation on a live (issued/response_received) RFQ can
    be declined; a supplier who already quoted has, by definition, not
    declined."""
    if invitation.rfq_id != rfq.id:
        raise BusinessRuleError("This invitation does not belong to this RFQ.")
    if rfq.status not in (ISSUED, RESPONSE_RECEIVED):
        raise BusinessRuleError("Can only decline an invitation on an issued RFQ.")
    if invitation.status != INVITATION_SENT:
        raise BusinessRuleError(f"Cannot decline an invitation that is already '{invitation.status}'.")
    invitation.status = INVITATION_DECLINED


def add_follow_up(
    db: Session, *, rfq: Rfq, invitation: RfqSupplierInvitation, note: str, created_by_user_id: int | None
) -> RfqInvitationFollowUp:
    """Gap-fix: supplier follow-up -- a simple, append-only note against
    one invited supplier, same "record what happened" gate as
    decline_invitation (a live RFQ only; nothing to follow up on a
    draft, and a decided/cancelled/converted RFQ is already history)."""
    if invitation.rfq_id != rfq.id:
        raise BusinessRuleError("This invitation does not belong to this RFQ.")
    if rfq.status not in (ISSUED, RESPONSE_RECEIVED):
        raise BusinessRuleError("Can only record a follow-up on an issued RFQ.")

    follow_up = RfqInvitationFollowUp(invitation_id=invitation.id, note=note, created_by_user_id=created_by_user_id)
    db.add(follow_up)
    db.flush()
    return follow_up


def decide(
    db: Session,
    *,
    rfq: Rfq,
    decision: str,
    selected_response_id: int | None,
    decision_note: str | None,
    decided_by_user_id: int | None,
) -> None:
    """docs/modules/rfq.md #7 -- only valid from response_received.
    `selected_response_id` is required when selecting, and must reference
    a response captured against any invitation on *this* RFQ. The
    accepted-quotation files are attached by the caller in the same
    transaction. `rejected` is terminal: nothing further can happen."""
    if rfq.status != RESPONSE_RECEIVED:
        raise BusinessRuleError("A decision can only be made once a supplier response has been received.")

    if decision == SELECTED:
        if selected_response_id is None:
            raise ValidationError(
                "selected_response_id is required when selecting a response.",
                fields={"selected_response_id": "Required when decision is 'selected'."},
            )
        response = (
            db.query(RfqResponse)
            .join(RfqSupplierInvitation, RfqSupplierInvitation.id == RfqResponse.invitation_id)
            .filter(RfqResponse.id == selected_response_id, RfqSupplierInvitation.rfq_id == rfq.id)
            .first()
        )
        if response is None:
            raise ValidationError(
                "selected_response_id must reference a response captured on this RFQ.",
                fields={"selected_response_id": "Not a response on this RFQ."},
            )
        rfq.selected_response_id = response.id
    else:
        rfq.selected_response_id = None

    rfq.status = decision
    rfq.decided_by_user_id = decided_by_user_id
    rfq.decided_at = datetime.utcnow()
    rfq.decision_note = decision_note
    db.add(rfq)


def get_invitation_for_response(db: Session, rfq: Rfq, response_id: int | None) -> RfqSupplierInvitation:
    """The invitation behind a captured response on this RFQ -- the PO's
    supplier source (docs/modules/rfq.md #8). `response_id` defaults to
    the RFQ's own decided response, but converting to a Purchase Order a
    second time can name a different one of this RFQ's own captured
    responses, to source the remaining quantity from another supplier
    (gap-fix: split sourcing) -- it still must belong to an invitation on
    *this* RFQ, the same check `decide` applies when selecting."""
    if response_id is None:
        raise BusinessRuleError("This RFQ has no selected supplier response to convert.")
    invitation = (
        db.query(RfqSupplierInvitation)
        .join(RfqResponse, RfqResponse.invitation_id == RfqSupplierInvitation.id)
        .filter(RfqResponse.id == response_id, RfqSupplierInvitation.rfq_id == rfq.id)
        .first()
    )
    if invitation is None:
        raise ValidationError(
            "response_id must reference a response captured on this RFQ.",
            fields={"response_id": "Not a response on this RFQ."},
        )
    return invitation


def line_requested_in_material_units(
    rfq_line: RfqLine, material: RawMaterial, units: dict[int, UnitOfMeasure]
) -> Decimal:
    """The RFQ line's own requested quantity, normalised to the
    material's own unit -- the same basis a Purchase Order line's
    `quantity * conversion_factor` already uses, so "how much of this
    line has been sourced" can be compared to "how much was asked for"
    on one scale, whatever unit a particular supplier quoted or was
    purchased in (gap-fix: split sourcing)."""
    if rfq_line.unit_of_measure_id == material.unit_of_measure_id:
        return rfq_line.quantity
    ratio = line_unit_ratio(
        units[rfq_line.unit_of_measure_id],
        material,
        units.get(material.alternate_conversion_unit_of_measure_id),
        units[material.unit_of_measure_id],
    )
    if ratio is None:
        raise BusinessRuleError(
            f"{material.name}: its requested unit no longer converts to its unit. Update the unit setup first."
        )
    return rfq_line.quantity * ratio


def sourced_quantities(db: Session, rfq_line_ids: list[int]) -> dict[int, Decimal]:
    """How much of each given RFQ line has already been put on a
    Purchase Order (any status -- once ordered, it counts as sourced),
    normalised to the material's own unit via each PO line's own
    `conversion_factor` (gap-fix: split sourcing)."""
    if not rfq_line_ids:
        return {}
    totals: dict[int, Decimal] = {}
    rows = (
        db.query(PurchaseOrderLine.rfq_line_id, PurchaseOrderLine.quantity, PurchaseOrderLine.conversion_factor)
        .filter(PurchaseOrderLine.rfq_line_id.in_(rfq_line_ids))
        .all()
    )
    for rfq_line_id, quantity, conversion_factor in rows:
        totals[rfq_line_id] = totals.get(rfq_line_id, Decimal(0)) + quantity * conversion_factor
    return totals


def _rfq_line_conversion_context(
    db: Session, rfq_lines: list[RfqLine]
) -> tuple[dict[int, RawMaterial], dict[int, UnitOfMeasure]]:
    """Every material and unit a set of RFQ lines could need to convert
    against its own unit -- shared by is_fully_sourced and
    line_sourced_quantities (gap-fix: split sourcing)."""
    materials = {
        m.id: m for m in db.query(RawMaterial).filter(RawMaterial.id.in_({l.raw_material_id for l in rfq_lines}))
    }
    unit_ids = {l.unit_of_measure_id for l in rfq_lines} | {m.unit_of_measure_id for m in materials.values()} | {
        m.alternate_conversion_unit_of_measure_id for m in materials.values() if m.alternate_conversion_unit_of_measure_id
    }
    units = {u.id: u for u in db.query(UnitOfMeasure).filter(UnitOfMeasure.id.in_(unit_ids))}
    return materials, units


def is_fully_sourced(db: Session, rfq: Rfq) -> bool:
    """Every line's full requested quantity has been put on a Purchase
    Order converted from this RFQ -- the gate for moving the RFQ to its
    terminal `converted` status. While any line still has quantity
    remaining, the RFQ stays `selected`: open to converting again,
    naming another of its captured responses, to source the rest
    (gap-fix: split sourcing)."""
    rfq_lines = db.query(RfqLine).filter(RfqLine.rfq_id == rfq.id).all()
    if not rfq_lines:
        return True
    materials, units = _rfq_line_conversion_context(db, rfq_lines)
    sourced = sourced_quantities(db, [l.id for l in rfq_lines])
    for line in rfq_lines:
        try:
            requested = line_requested_in_material_units(line, materials[line.raw_material_id], units)
        except BusinessRuleError:
            # A different, unconverted line's unit setup broke since the
            # RFQ was created -- never let that block or unwind a
            # conversion that has already correctly gone through for
            # another line; it just means this RFQ isn't fully sourced.
            return False
        if sourced.get(line.id, Decimal(0)) < requested:
            return False
    return True


def line_sourced_quantities(db: Session, rfq_lines: list[RfqLine]) -> dict[int, Decimal]:
    """Each given RFQ line's sourced quantity so far, converted back into
    that line's own requested unit (matching RfqLine.quantity/
    unit_of_measure_id) -- for the "how much has been sourced, how much
    remains" display (gap-fix: split sourcing)."""
    if not rfq_lines:
        return {}
    materials, units = _rfq_line_conversion_context(db, rfq_lines)
    sourced_in_material_units = sourced_quantities(db, [l.id for l in rfq_lines])
    result: dict[int, Decimal] = {}
    for line in rfq_lines:
        sourced = sourced_in_material_units.get(line.id, Decimal(0))
        material = materials[line.raw_material_id]
        if sourced != 0 and line.unit_of_measure_id != material.unit_of_measure_id:
            ratio = line_unit_ratio(
                units[line.unit_of_measure_id],
                material,
                units.get(material.alternate_conversion_unit_of_measure_id),
                units[material.unit_of_measure_id],
            )
            if ratio:
                sourced = sourced / ratio
        result[line.id] = sourced.quantize(Decimal("0.0001"))
    return result


def resolve_conversion_prices(
    db: Session, *, rfq: Rfq, response_id: int, overrides: dict[int, Decimal | None] | None
) -> list[tuple[RfqLine, Decimal, Decimal | None, int | None]]:
    """docs/modules/rfq.md #8. `response_id` is a response captured on
    this RFQ -- normally its decided one, but converting a second time
    can name another to source the rest from a different supplier
    (gap-fix: split sourcing). `overrides is None` -> every RFQ line, at
    that response's quoted price. Otherwise exactly the listed lines,
    each at its override price, or the quoted one when no override is
    given. A line with neither is rejected, naming the line -- a price
    is never guessed.

    Also resolves each line's quoted quantity (the third tuple element) --
    None when the selected response quoted no explicit quantity for that
    line (the RFQ line's own requested quantity applies), otherwise the
    quantity the supplier actually agreed to (gap-fix: partial
    quotation must carry through to the PO, not just be recorded and
    ignored) -- and each line's quoted unit of measure (the fourth tuple
    element) -- None when the selected response quoted in the RFQ line's
    own unit, otherwise the unit the supplier actually quoted in (gap-fix:
    supplier UOM mismatch must carry through to the PO)."""
    rfq_lines = db.query(RfqLine).filter(RfqLine.rfq_id == rfq.id).order_by(RfqLine.id).all()
    if overrides is not None:
        lines_by_id = {line.id: line for line in rfq_lines}
        if any(line_id not in lines_by_id for line_id in overrides):
            raise ValidationError("One or more lines do not belong to this RFQ.")
        rfq_lines = [lines_by_id[line_id] for line_id in overrides]
    if not rfq_lines:
        raise BusinessRuleError("This RFQ has no lines to convert.")

    quoted_rows = (
        db.query(
            RfqResponseLine.rfq_line_id,
            RfqResponseLine.unit_price,
            RfqResponseLine.quantity,
            RfqResponseLine.unit_of_measure_id,
        )
        .filter(RfqResponseLine.response_id == response_id)
        .all()
    )
    quoted_prices = {row.rfq_line_id: row.unit_price for row in quoted_rows}
    quoted_quantities = {row.rfq_line_id: row.quantity for row in quoted_rows}
    quoted_units = {row.rfq_line_id: row.unit_of_measure_id for row in quoted_rows}

    resolved: list[tuple[RfqLine, Decimal, Decimal | None, int | None]] = []
    missing: list[int] = []
    for line in rfq_lines:
        price = (overrides or {}).get(line.id) or quoted_prices.get(line.id)
        if price is None:
            missing.append(line.id)
        else:
            resolved.append((line, price, quoted_quantities.get(line.id), quoted_units.get(line.id)))
    if missing:
        raise ValidationError(
            "Enter a unit price for every line the selected supplier did not quote.",
            fields={"lines": f"No quoted price for RFQ line(s): {', '.join(str(i) for i in missing)}."},
        )
    return resolved


@dataclass
class RfqConversionLine:
    """Kept in the RFQ line's own unit; `conversion_factor` is
    `1 unit = factor material units` for receiving."""

    raw_material: RawMaterial
    quantity: Decimal
    unit_price: Decimal
    unit_of_measure_id: int
    conversion_factor: Decimal
    required_by_date: date | None
    remarks: str | None
    # Which RFQ line this was converted from -- carried onto the PO line
    # so several suppliers' POs against the same line can be added back
    # up (gap-fix: split sourcing).
    rfq_line_id: int


def convert_to_purchase_order(
    db: Session,
    *,
    rfq: Rfq,
    supplier_id: int,
    expected_delivery_date: date,
    payment_terms: str,
    supplier_reference: str | None,
    notes: str | None,
    lines: list[RfqConversionLine],
    rfq_response_id: int | None,
    created_by_user_id: int | None,
) -> PurchaseOrder:
    """docs/modules/rfq.md #8/#14 -- only valid from `selected`. Supplier
    comes from the given response's invitation; each line's material and
    quantity carry forward from the RFQ untouched. Built on the same
    app/services/purchase_order_service.create_purchase_order_with_lines
    the plain "New Purchase" flow uses -- one transaction, caller
    commits.

    Callable more than once on the same RFQ: each call sources the given
    lines from one response (one supplier), for up to what remains
    unsourced on each (the caller already checked this) -- gap-fix: split
    sourcing. The RFQ only reaches its terminal `converted` status, and
    stops accepting further conversions, once every line's full
    requested quantity has been sourced across all of its Purchase
    Orders; until then it stays `selected`."""
    assert_transition_allowed(rfq.status, CONVERTED)

    purchase_order = purchase_order_service.create_purchase_order_with_lines(
        db,
        organisation_id=rfq.organisation_id,
        supplier_id=supplier_id,
        order_date=date.today(),
        expected_delivery_date=expected_delivery_date,
        notes=notes or f"Converted from RFQ {rfq.rfq_number}.",
        rfq_id=rfq.id,
        rfq_response_id=rfq_response_id,
        # The PO keeps the final agreed terms as its own values -- never
        # read back from the quotation later.
        payment_terms=payment_terms,
        supplier_reference=supplier_reference,
        created_by_user_id=created_by_user_id,
        lines=[
            purchase_order_service.PurchaseOrderLineInput(
                raw_material=line.raw_material,
                quantity=line.quantity,
                unit_price=line.unit_price,
                unit_of_measure_id=line.unit_of_measure_id,
                conversion_factor=line.conversion_factor,
                required_by_date=line.required_by_date,
                remarks=line.remarks,
                rfq_line_id=line.rfq_line_id,
            )
            for line in lines
        ],
    )

    # The first conversion's PO is kept as the header's own reference;
    # every PO converted from this RFQ (this one included) is always
    # available via PurchaseOrder.rfq_id for full traceability.
    if rfq.purchase_order_id is None:
        rfq.purchase_order_id = purchase_order.id
    if is_fully_sourced(db, rfq):
        rfq.status = CONVERTED
    db.add(rfq)
    return purchase_order
