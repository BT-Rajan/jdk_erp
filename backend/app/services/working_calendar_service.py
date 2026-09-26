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
- A required date that is itself non-working (Friday, Saturday or a
  holiday) is `not_servable`: not a normal delivery date. It is a
  result, not an error -- a later Sales workflow sends it to Admin.
  The requested date is never moved.
- The applicable working day is today while the current Kuwait time is
  at or before the organisation's `same_day_cutoff_time` (14:00 by
  default); after the cut-off it is the next working day (Sales S5).
- A required date equal to the applicable working day is same day.
  Otherwise count only working days after the applicable day, up to
  and including the required date: 0-2 -> within 2 working days, 3 or
  more -> more than 2 working days. (A request for today made after the
  cut-off falls before the applicable day: 0 working days after it,
  i.e. within 2 working days.)
- Time-dependent by nature: computed from the current Kuwait time on
  every call, never stored here.

A date before today is not classified at all -> ValidationError.

Read-only: nothing here writes, commits, or touches any Sales,
inventory or production record."""

from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.errors import ValidationError
from app.core.timezone import now_jdk, to_jdk_time
from app.models.organisation import Organisation
from app.models.organisation_holiday import OrganisationHoliday

# date.weekday(): Monday=0 ... Sunday=6.
WORKING_WEEKDAYS = frozenset({6, 0, 1, 2, 3})  # Sunday-Thursday
WORKING_WEEKDAY_NAMES = ("sunday", "monday", "tuesday", "wednesday", "thursday")

SAME_DAY = "same_day"
WITHIN_2_WORKING_DAYS = "within_2_working_days"
MORE_THAN_2_WORKING_DAYS = "more_than_2_working_days"
NOT_SERVABLE = "not_servable"
DELIVERY_WINDOWS = (SAME_DAY, WITHIN_2_WORKING_DAYS, MORE_THAN_2_WORKING_DAYS, NOT_SERVABLE)

_WITHIN_WORKING_DAYS_LIMIT = 2
# Holidays are fetched this far past a missed cut-off's "today" when
# looking for the next working day -- far longer than any real run of
# consecutive non-working days.
_NEXT_WORKING_DAY_HORIZON_DAYS = 31


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


def next_working_day(day: date, holidays: set[date]) -> date:
    """The first working day strictly after `day`."""
    candidate = day + timedelta(days=1)
    while not is_working_day(candidate, holidays):
        candidate += timedelta(days=1)
    return candidate


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

    if not is_working_day(required_date, get_holiday_dates(db, organisation_id, required_date, required_date)):
        return NOT_SERVABLE

    cutoff = db.query(Organisation.same_day_cutoff_time).filter(Organisation.id == organisation_id).scalar()
    evaluation_start = today
    if current.time() > cutoff:
        # Missed the cut-off: the request is evaluated from the next
        # working day, whatever date it asks for. The requested date
        # itself is never changed.
        evaluation_start = next_working_day(
            today,
            get_holiday_dates(db, organisation_id, today, today + timedelta(days=_NEXT_WORKING_DAY_HORIZON_DAYS)),
        )

    if required_date == evaluation_start:
        return SAME_DAY

    holidays = get_holiday_dates(db, organisation_id, evaluation_start + timedelta(days=1), required_date)
    if count_working_days_after(evaluation_start, required_date, holidays) <= _WITHIN_WORKING_DAYS_LIMIT:
        return WITHIN_2_WORKING_DAYS
    return MORE_THAN_2_WORKING_DAYS
