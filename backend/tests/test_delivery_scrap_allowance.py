"""Delivery Scrap Allowance %: an organisation-level, Admin-only setting
(PATCH /api/organisations/me), default 0, never negative, audited with
old -> new values. Only the setting -- no Delivery behaviour exists yet."""

from decimal import Decimal

from app.models.audit_event import ORGANISATION_UPDATED, AuditEvent
from app.models.organisation import Organisation


def _headers(client, username):
    login = client.post("/api/auth/login", json={"username": username, "password": "Str0ng!Pass"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _set(client, headers, value):
    return client.patch("/api/organisations/me", json={"delivery_scrap_allowance_percent": value}, headers=headers)


def test_default_is_zero(client, db_session, organisation, admin_user):
    assert db_session.get(Organisation, organisation.id).delivery_scrap_allowance_percent == Decimal("0")
    body = client.get("/api/organisations/me", headers=_headers(client, "admin_person")).json()
    assert Decimal(body["delivery_scrap_allowance_percent"]) == Decimal("0")


def test_admin_reads_and_changes_it(client, db_session, organisation, admin_user):
    admin = _headers(client, "admin_person")
    response = _set(client, admin, "2.5")
    assert response.status_code == 200
    assert Decimal(response.json()["delivery_scrap_allowance_percent"]) == Decimal("2.5")
    assert Decimal(client.get("/api/organisations/me", headers=admin).json()["delivery_scrap_allowance_percent"]) == Decimal("2.5")
    db_session.expire_all()
    assert db_session.get(Organisation, organisation.id).delivery_scrap_allowance_percent == Decimal("2.50")


def test_invalid_values_are_rejected_server_side(client, db_session, organisation, admin_user):
    admin = _headers(client, "admin_person")
    # Negative, more than 2 decimal places (never silently rounded), too
    # large to store, and an explicit null are all refused.
    for value in ("-1", "-0.01", "2.555", "1000", None, "abc"):
        assert _set(client, admin, value).status_code == 422, value
    db_session.expire_all()
    assert db_session.get(Organisation, organisation.id).delivery_scrap_allowance_percent == Decimal("0")


def test_non_admins_cannot_change_it(client, db_session, organisation, active_user, manager_user):
    for user in (active_user, manager_user):
        assert _set(client, _headers(client, user.username), "5").status_code == 403
    db_session.expire_all()
    assert db_session.get(Organisation, organisation.id).delivery_scrap_allowance_percent == Decimal("0")


def test_change_is_audited_with_old_and_new_values(client, db_session, organisation, admin_user):
    admin = _headers(client, "admin_person")
    _set(client, admin, "3")
    _set(client, admin, "3.00")  # same value: no second audit entry
    _set(client, admin, "4.25")
    events = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.action == ORGANISATION_UPDATED, AuditEvent.organisation_id == organisation.id)
        .order_by(AuditEvent.id)
        .all()
    )
    assert [e.details for e in events] == [
        "delivery_scrap_allowance_percent: 0.00 -> 3.00",
        "delivery_scrap_allowance_percent: 3.00 -> 4.25",
    ]
    assert all(e.actor_user_id == admin_user.id and e.created_at is not None for e in events)
