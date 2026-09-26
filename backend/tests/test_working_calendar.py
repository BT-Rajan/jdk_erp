"""Sales S1: the organisation working calendar (Sunday-Thursday, Kuwait
time, Admin-configured holidays and same-day cut-off) and the
delivery-window classifier built on it
(app/services/working_calendar_service.py)."""

from datetime import date, datetime, timezone

from app.models.audit_event import HOLIDAY_ADDED, SAME_DAY_CUTOFF_UPDATED, AuditEvent
from app.models.organisation_holiday import OrganisationHoliday
from app.services.working_calendar_service import (
    MORE_THAN_2_WORKING_DAYS,
    NOT_SERVABLE,
    SAME_DAY,
    WITHIN_2_WORKING_DAYS,
    classify_delivery_window,
    next_working_day,
)

MONDAY = date(2026, 9, 28)
TUESDAY = date(2026, 9, 29)
WEDNESDAY = date(2026, 9, 30)
THURSDAY = date(2026, 10, 1)
# 09:00 Kuwait (UTC+3) on each day.
MONDAY_MORNING_UTC = datetime(2026, 9, 28, 6, 0, tzinfo=timezone.utc)
THURSDAY_MORNING_UTC = datetime(2026, 10, 1, 6, 0, tzinfo=timezone.utc)


def _admin_headers(client):
    login = client.post("/api/auth/login", json={"username": "admin_person", "password": "Str0ng!Pass"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_working_days_skip_friday_saturday_and_holidays(db_session, organisation):
    classify = lambda required, now: classify_delivery_window(db_session, organisation.id, required, now=now)

    # Today is never counted: Mon -> Tue = 1, Mon -> Wed = 2, Mon -> Thu = 3.
    assert classify(TUESDAY, MONDAY_MORNING_UTC) == WITHIN_2_WORKING_DAYS
    assert classify(WEDNESDAY, MONDAY_MORNING_UTC) == WITHIN_2_WORKING_DAYS
    assert classify(THURSDAY, MONDAY_MORNING_UTC) == MORE_THAN_2_WORKING_DAYS
    # Friday and Saturday are skipped: Thu -> next Mon = Sun + Mon = 2.
    assert classify(date(2026, 10, 5), THURSDAY_MORNING_UTC) == WITHIN_2_WORKING_DAYS
    assert classify(date(2026, 10, 6), THURSDAY_MORNING_UTC) == MORE_THAN_2_WORKING_DAYS

    # A holiday is non-working too: with Tuesday off, Mon -> Thu = 2.
    db_session.add(OrganisationHoliday(organisation_id=organisation.id, holiday_date=TUESDAY, description="Holiday"))
    db_session.commit()
    assert classify(THURSDAY, MONDAY_MORNING_UTC) == WITHIN_2_WORKING_DAYS


def test_non_working_required_date_is_not_servable(db_session, organisation):
    """A Friday, Saturday or holiday is not a normal delivery date --
    returned as a result (never an error), and never moved to another day."""
    db_session.add(OrganisationHoliday(organisation_id=organisation.id, holiday_date=TUESDAY, description="Holiday"))
    db_session.commit()
    classify = lambda required: classify_delivery_window(db_session, organisation.id, required, now=MONDAY_MORNING_UTC)

    assert classify(date(2026, 10, 2)) == NOT_SERVABLE  # Friday
    assert classify(date(2026, 10, 3)) == NOT_SERVABLE  # Saturday
    assert classify(TUESDAY) == NOT_SERVABLE  # holiday
    assert classify(WEDNESDAY) == WITHIN_2_WORKING_DAYS


def test_same_day_uses_kuwait_time_and_the_configured_cutoff(client, db_session, admin_user, organisation):
    # The organisation's own display timezone is UTC here; the decision
    # must still be made in Kuwait time.
    assert organisation.timezone == "UTC"
    classify = lambda now: classify_delivery_window(db_session, organisation.id, MONDAY, now=now)

    # 10:59 UTC = 13:59 Kuwait -> before the default 14:00 cut-off.
    assert classify(datetime(2026, 9, 28, 10, 59, tzinfo=timezone.utc)) == SAME_DAY
    # Sunday 21:30 UTC is already Monday 00:30 in Kuwait.
    assert classify(datetime(2026, 9, 27, 21, 30, tzinfo=timezone.utc)) == SAME_DAY
    # 11:00 UTC = exactly 14:00 Kuwait -> still at the cut-off.
    assert classify(datetime(2026, 9, 28, 11, 0, tzinfo=timezone.utc)) == SAME_DAY
    # 11:01 UTC = 14:01 Kuwait -> past the cut-off: no longer same day,
    # evaluated from the next working day (Tuesday).
    after_cutoff = datetime(2026, 9, 28, 11, 1, tzinfo=timezone.utc)
    assert classify(after_cutoff) == WITHIN_2_WORKING_DAYS
    # "Next working day" skips Friday, Saturday and holidays: Thursday's
    # next working day is Monday when Sunday is a holiday.
    assert next_working_day(THURSDAY, {date(2026, 10, 4)}) == date(2026, 10, 5)

    response = client.put(
        "/api/organisations/me/working-calendar/cutoff",
        json={"same_day_cutoff_time": "16:00"},
        headers=_admin_headers(client),
    )
    assert response.status_code == 200
    assert response.json()["same_day_cutoff_time"] == "16:00:00"
    db_session.expire_all()
    assert classify(after_cutoff) == SAME_DAY


def test_admin_manages_cutoff_and_holidays_with_validation(client, db_session, admin_user, organisation):
    headers = _admin_headers(client)

    calendar = client.get("/api/organisations/me/working-calendar", headers=headers).json()
    assert calendar["working_days"] == ["sunday", "monday", "tuesday", "wednesday", "thursday"]
    assert calendar["timezone"] == "Asia/Kuwait"
    assert calendar["same_day_cutoff_time"] == "14:00:00"
    assert calendar["holidays"] == []

    bad_time = client.put(
        "/api/organisations/me/working-calendar/cutoff", json={"same_day_cutoff_time": "25:00"}, headers=headers
    )
    assert bad_time.status_code == 422

    holidays_url = "/api/organisations/me/working-calendar/holidays"
    bad_date = client.post(holidays_url, json={"holiday_date": "2026-02-30", "description": "X"}, headers=headers)
    assert bad_date.status_code == 422

    created = client.post(holidays_url, json={"holiday_date": "2026-09-29", "description": "Holiday"}, headers=headers)
    assert created.status_code == 201
    duplicate = client.post(holidays_url, json={"holiday_date": "2026-09-29", "description": "Other"}, headers=headers)
    assert duplicate.status_code == 409
    assert db_session.query(OrganisationHoliday).one().description == "Holiday"
    assert db_session.query(AuditEvent).filter(AuditEvent.action == HOLIDAY_ADDED).count() == 1

    removed = client.delete(f"{holidays_url}/{created.json()['id']}", headers=headers)
    assert removed.status_code == 204
    assert client.get("/api/organisations/me/working-calendar", headers=headers).json()["holidays"] == []


def test_only_own_organisation_admin_can_change_the_calendar(
    client, db_session, active_user, admin_user, organisation, other_organisation
):
    login = client.post("/api/auth/login", json={"username": "ada", "password": "Str0ng!Pass"})
    member_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    base = "/api/organisations/me/working-calendar"

    assert client.get(base, headers=member_headers).status_code == 200
    assert (
        client.put(f"{base}/cutoff", json={"same_day_cutoff_time": "18:00"}, headers=member_headers).status_code
        == 403
    )
    assert (
        client.post(
            f"{base}/holidays", json={"holiday_date": "2026-09-29", "description": "X"}, headers=member_headers
        ).status_code
        == 403
    )

    foreign = OrganisationHoliday(organisation_id=other_organisation.id, holiday_date=TUESDAY, description="Theirs")
    db_session.add(foreign)
    db_session.commit()
    assert client.delete(f"{base}/holidays/{foreign.id}", headers=member_headers).status_code == 403
    assert client.delete(f"{base}/holidays/{foreign.id}", headers=_admin_headers(client)).status_code == 404

    db_session.expire_all()
    assert db_session.get(type(organisation), organisation.id).same_day_cutoff_time.strftime("%H:%M") == "14:00"
    assert db_session.query(OrganisationHoliday).count() == 1
    assert db_session.query(AuditEvent).filter(AuditEvent.action == SAME_DAY_CUTOFF_UPDATED).count() == 0
