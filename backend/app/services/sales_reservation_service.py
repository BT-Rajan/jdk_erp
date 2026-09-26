"""Customer reservations: the commercial commitment of an accepted quotation
(Reservation + FG Allocation foundation). Not physical stock -- nothing
here reads or writes Finished Goods -- and never production demand.

Lifecycle, driven by the existing Sales flow only:
- accept a quotation -> one `active` reservation per line;
- Admin edits an accepted quotation -> reservations follow its lines
  (changed in place, added, or released for removed lines);
- convert -> the same reservations are linked to their Sales Order lines;
- Admin changes an order line's quantity -> its reservation follows;
- an order line delivered in full -> `fulfilled`;
- the order cancelled (or the quotation released) -> `released`.

Does not audit or commit: callers log each returned ReservationChange."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.fg_allocation import RESERVATION_ACTIVE, RESERVATION_FULFILLED, RESERVATION_RELEASED, SalesReservation
from app.models.quotation import Quotation
from app.models.sales_order import SalesOrder, SalesOrderLine


@dataclass(frozen=True)
class ReservationChange:
    reservation: SalesReservation
    kind: str  # created | changed | released | fulfilled
    details: str


def _plain(value: Decimal) -> str:
    return format(Decimal(value).normalize(), "f")


def _active(db: Session, **filters) -> list[SalesReservation]:
    query = db.query(SalesReservation).filter(SalesReservation.status == RESERVATION_ACTIVE)
    for field, value in filters.items():
        query = query.filter(getattr(SalesReservation, field) == value)
    return query.order_by(SalesReservation.line_number).with_for_update().all()


def reserve_for_quotation(db: Session, quotation: Quotation) -> list[ReservationChange]:
    """On acceptance: one active reservation per quotation line."""
    changes = []
    for line in sorted(quotation.lines, key=lambda l: l.line_number):
        reservation = SalesReservation(
            organisation_id=quotation.organisation_id,
            quotation_id=quotation.id,
            line_number=line.line_number,
            product_id=line.product_id,
            unit_of_measure_id=line.unit_of_measure_id,
            quantity=line.quantity,
            status=RESERVATION_ACTIVE,
        )
        db.add(reservation)
        changes.append(ReservationChange(reservation, "created", f"line {line.line_number}: {_plain(line.quantity)}"))
    db.flush()
    return changes


def sync_for_quotation(db: Session, quotation: Quotation) -> list[ReservationChange]:
    """After an Admin edit of an accepted quotation: reservations follow its
    lines by line number -- changed in place, created, or released."""
    existing = {r.line_number: r for r in _active(db, quotation_id=quotation.id)}
    if not existing:
        return []
    changes = []
    lines = {line.line_number: line for line in quotation.lines}
    for number, line in sorted(lines.items()):
        reservation = existing.get(number)
        if reservation is None:
            continue
        old = (reservation.product_id, reservation.unit_of_measure_id, reservation.quantity)
        new = (line.product_id, line.unit_of_measure_id, line.quantity)
        if old != new:
            reservation.product_id, reservation.unit_of_measure_id, reservation.quantity = new
            changes.append(ReservationChange(
                reservation, "changed", f"line {number}: product {old[0]} -> {new[0]}, quantity {_plain(old[2])} -> {_plain(new[2])}"
            ))
    for number, line in sorted(lines.items()):
        if number not in existing:
            reservation = SalesReservation(
                organisation_id=quotation.organisation_id, quotation_id=quotation.id, line_number=number,
                product_id=line.product_id, unit_of_measure_id=line.unit_of_measure_id, quantity=line.quantity,
                status=RESERVATION_ACTIVE,
            )
            db.add(reservation)
            changes.append(ReservationChange(reservation, "created", f"line {number}: {_plain(line.quantity)}"))
    for number, reservation in existing.items():
        if number not in lines:
            changes.extend(_release([reservation], "quotation line removed"))
    db.flush()
    return changes


def _release(reservations: list[SalesReservation], reason: str) -> list[ReservationChange]:
    now = datetime.utcnow()
    changes = []
    for reservation in reservations:
        reservation.status = RESERVATION_RELEASED
        reservation.released_at = now
        reservation.release_reason = reason
        changes.append(ReservationChange(reservation, "released", f"line {reservation.line_number}: {reason}"))
    return changes


def release_for_quotation(db: Session, quotation: Quotation, reason: str) -> list[ReservationChange]:
    """A quotation withdrawn before conversion releases its reservations.
    (The existing lifecycle has no way to reject or cancel an *accepted*
    quotation; this is the operation such a path uses.)"""
    changes = _release(_active(db, quotation_id=quotation.id, sales_order_id=None), reason)
    db.flush()
    return changes


def link_to_order(db: Session, quotation: Quotation, order: SalesOrder) -> list[ReservationChange]:
    """On conversion: each active reservation now belongs to the order line
    with the same line number -- one commitment, traceable both ways."""
    order_lines = {line.line_number: line for line in order.lines}
    changes = []
    for reservation in _active(db, quotation_id=quotation.id):
        line = order_lines.get(reservation.line_number)
        if line is None:
            continue
        reservation.sales_order_id = order.id
        reservation.sales_order_line_id = line.id
        changes.append(ReservationChange(reservation, "changed", f"line {reservation.line_number}: linked to sales order {order.order_number}"))
    db.flush()
    return changes


def follow_line_quantity(db: Session, line: SalesOrderLine) -> ReservationChange | None:
    """After an Admin quantity change on an order line."""
    [reservation] = _active(db, sales_order_line_id=line.id) or [None]
    if reservation is None or reservation.quantity == line.quantity:
        return None
    before = reservation.quantity
    reservation.quantity = line.quantity
    db.flush()
    return ReservationChange(reservation, "changed", f"line {line.line_number}: quantity {_plain(before)} -> {_plain(line.quantity)}")


def release_for_order(db: Session, order: SalesOrder, reason: str) -> list[ReservationChange]:
    changes = _release(_active(db, sales_order_id=order.id), reason)
    db.flush()
    return changes


def mark_fulfilled(db: Session, order: SalesOrder, delivered: dict[int, Decimal]) -> list[ReservationChange]:
    """Order lines delivered in full: their commitment is met."""
    ordered = {line.id: line.quantity for line in order.lines}
    changes = []
    for reservation in _active(db, sales_order_id=order.id):
        line_id = reservation.sales_order_line_id
        if line_id in ordered and delivered.get(line_id, Decimal("0")) >= ordered[line_id]:
            reservation.status = RESERVATION_FULFILLED
            changes.append(ReservationChange(reservation, "fulfilled", f"line {reservation.line_number}: delivered"))
    db.flush()
    return changes
