"""The organisation's one working calendar and the Sales delivery-window
classifier built on it (Sales business contract, S1). Every later Sales
service classifies a required delivery date through
`classify_delivery_window` here -- never by re-deriving working days or
reading the clock itself.

Frozen rules:
- Working days are Sunday-Thursday; Friday and Saturday are not. This
  is a fixed business rule, not a setting, so it lives here as a
  constant. Admin-configured holidays (OrganisationHoliday) are also
  non-working.
- Every decision uses Kuwait server time (app/core/timezone.JDK_TIMEZONE),
  never the organisation's display `timezone` column and never a
  client-supplied time -- no API accepts "now" from the caller.
- Same day means the required date is today's Kuwait date and the
  current Kuwait time is at or before the organisation's
  `same_day_cutoff_time` (14:00 by default).
- For a later date, count only working days after today, up to and
  including the required date: 0-2 -> within 2 working days, 3 or more
  -> more than 2 working days.

Two inputs are deliberately NOT classified, because no business rule
for them exists yet and this service must not invent one:
- today's date after the same-day cut-off -> SameDayCutoffPassedError;
- a date before today -> ValidationError.

Read-only: nothing here writes, commits, or touches any Sales,
inventory or production record."""

from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleError, ValidationError
from app.core.timezone import now_jdk, to_jdk_time
from app.models.organisation import Organisation
from app.models.organisation_holiday import OrganisationHoliday

# date.weekday(): Monday=0 ... Sunday=6.
WORKING_WEEKDAYS = frozenset({6, 0, 1, 2, 3})  # Sunday-Thursday
WORKING_WEEKDAY_NAMES = ("sunday", "monday", "tuesday", "wednesday", "thursday")

SAME_DAY = "same_day"
WITHIN_2_WORKING_DAYS = "within_2_working_days"
MORE_THAN_2_WORKING_DAYS = "more_than_2_working_days"
DELIVERY_WINDOWS = (SAME_DAY, WITHIN_2_WORKING_DAYS, MORE_THAN_2_WORKING_DAYS)

_WITHIN_WORKING_DAYS_LIMIT = 2


class SameDayCutoffPassedError(BusinessRuleError):
    """Today's date was requested after the same-day cut-off. There is no
    agreed business classification for this case yet (Sales S1 open
    decision), so it is refused rather than guessed."""


def is_working_day(day: date, holidays: set[date]) -> bool:
    return day.weekday() in WORKING_WEEKDAYS and day not in holidays


def get_holiday_dates(db: Session, organisation_id: int, start: date, end: date) -> set[date]:
    rows = (
        db.query(OrganisationHoliday.holiday_date)
        .filter(
            OrganisationHoliday.organisation_id == organisation_id,
            OrganisationHoliday.holiday_date >= start,
            OrganisationHoliday.holiday_date <= end,
        )
        .all()
    )
    return {row[0] for row in rows}


def count_working_days_after(today: date, until: date, holidays: set[date]) -> int:
    """Working days strictly after `today`, up to and including `until`."""
    count = 0
    day = today + timedelta(days=1)
    while day <= until:
        if is_working_day(day, holidays):
            count += 1
            if count > _WITHIN_WORKING_DAYS_LIMIT:
                # Only "more than 2" matters beyond this point; a far-off
                # date needn't be walked day by day.
                break
        day += timedelta(days=1)
    return count


def classify_delivery_window(
    db: Session, organisation_id: int, required_date: date, now: datetime | None = None
) -> str:
    """Returns exactly one of DELIVERY_WINDOWS. `now` exists for
    server-side callers and tests; it is converted to Kuwait time
    whatever zone it carries, and defaults to the current Kuwait time."""
    current = to_jdk_time(now) if now is not None else now_jdk()
    today = current.date()

    if required_date < today:
        raise ValidationError(
            "The required delivery date is in the past.", fields={"required_date": "Must be today or later."}
        )

    if required_date == today:
        cutoff = (
            db.query(Organisation.same_day_cutoff_time).filter(Organisation.id == organisation_id).scalar()
        )
        if current.time() <= cutoff:
            return SAME_DAY
        raise SameDayCutoffPassedError(
            f"Same-day delivery cut-off ({cutoff.strftime('%H:%M')} Kuwait time) has passed; "
            "no business rule yet defines how a later same-day request is classified."
        )

    holidays = get_holiday_dates(db, organisation_id, today + timedelta(days=1), required_date)
    if count_working_days_after(today, required_date, holidays) <= _WITHIN_WORKING_DAYS_LIMIT:
        return WITHIN_2_WORKING_DAYS
    return MORE_THAN_2_WORKING_DAYS

