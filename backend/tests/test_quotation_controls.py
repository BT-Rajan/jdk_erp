"""Sales S11.2: owner-only quotation editing, and a feasibility result
going stale when time moves the requested date into another window."""

from datetime import date, datetime
from decimal import Decimal

import pytest

from app.api import quotations as quotations_api
from app.core.roles import ADMIN, MANAGER, TEAM_MEMBER
from app.core.security import hash_password
from app.core.timezone import JDK_TIMEZONE
from app.models.customer import Customer
from app.models.team import Team
from app.models.user import User
from app.models.user_team import UserTeam
from app.services import feasibility_record_service, quotation_readiness_service, working_calendar_service

CLOCK = {"now": datetime(2026, 9, 28, 9, 0, tzinfo=JDK_TIMEZONE)}  # Monday 09:00 Kuwait
TUESDAY = date(2026, 9, 29)


def _user(db_session, organisation, username, role):
    user = User(
        organisation_id=organisation.id, role=role, full_name=username.title(), email=f"{username}@example.com",
        username=username, password_hash=hash_password("Str0ng!Pass"), is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    return user


def _headers(client, username):
    login = client.post("/api/auth/login", json={"username": username, "password": "Str0ng!Pass"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.fixture()
def setup(db_session, organisation, widget_product, monkeypatch):
    CLOCK["now"] = datetime(2026, 9, 28, 9, 0, tzinfo=JDK_TIMEZONE)
    for module in (working_calendar_service, quotations_api, feasibility_record_service, quotation_readiness_service):
        monkeypatch.setattr(module, "now_jdk", lambda: CLOCK["now"])
    team = Team(organisation_id=organisation.id, name="Sales", code="SALES", is_active=True)
    db_session.add(team)
    db_session.commit()
    users = {
        "head": _user(db_session, organisation, "head", MANAGER),
        "a": _user(db_session, organisation, "salesman_a", TEAM_MEMBER),
        "b": _user(db_session, organisation, "salesman_b", TEAM_MEMBER),
        "admin": _user(db_session, organisation, "boss", ADMIN),
    }
    db_session.add_all([UserTeam(user_id=users[k].id, team_id=team.id) for k in ("head", "a", "b")])
    customers = {
        "a": Customer(organisation_id=organisation.id, code="300001", name="A Co", assigned_to_user_id=users["a"].id),
        "head": Customer(organisation_id=organisation.id, code="300002", name="Head Co", assigned_to_user_id=users["head"].id),
    }
    db_session.add_all(customers.values())
    widget_product.min_selling_price = Decimal("90")
    widget_product.max_selling_price = Decimal("110")
    db_session.commit()
    return users, customers, widget_product


def _line(product, quantity="5"):
    return {"product_id": product.id, "quantity": quantity, "unit_of_measure_id": product.unit_of_measure_id, "unit_price": "100"}


def test_only_the_owning_salesman_can_edit(client, db_session, setup):
    users, customers, widget = setup
    body = {"customer_id": customers["a"].id, "requested_delivery_date": "2026-10-05", "lines": [_line(widget)]}
    quotation = client.post("/api/quotations", json=body, headers=_headers(client, "salesman_a")).json()
    url = f"/api/quotations/{quotation['id']}"
    edit = {"lines": [_line(widget, "6")]}

    assert client.get(url, headers=_headers(client, "salesman_a")).json()["can_edit"] is True
    for username in ("head", "boss"):
        assert client.get(url, headers=_headers(client, username)).json()["can_edit"] is False
        assert client.patch(url, json=edit, headers=_headers(client, username)).status_code == 403
    assert client.patch(url, json=edit, headers=_headers(client, "salesman_a")).status_code == 200

    # A quotation can't be moved onto a customer the editor doesn't own
    # (the head's customer is outside the salesman's scope: 404).
    assert client.patch(url, json={"customer_id": customers["head"].id}, headers=_headers(client, "salesman_a")).status_code == 404

    # Ownership follows the customer: after reassignment the new owner edits.
    customers["a"].assigned_to_user_id = users["b"].id
    db_session.commit()
    assert client.patch(url, json=edit, headers=_headers(client, "salesman_a")).status_code == 404
    assert client.patch(url, json={"lines": [_line(widget, "7")]}, headers=_headers(client, "salesman_b")).status_code == 200


def test_result_goes_stale_when_time_changes_the_window(client, setup):
    users, customers, widget = setup
    body = {"customer_id": customers["a"].id, "requested_delivery_date": TUESDAY.isoformat(), "lines": [_line(widget, "1")]}
    quotation_id = client.post("/api/quotations", json=body, headers=_headers(client, "salesman_a")).json()["id"]
    base = f"/api/quotations/{quotation_id}"
    a, admin = _headers(client, "salesman_a"), _headers(client, "boss")

    # Monday: Tuesday is within 2 working days; no FG and no BOM -> Admin approves.
    check = client.post(f"{base}/feasibility-checks", headers=a).json()
    assert (check["delivery_window"], check["state"]) == ("within_2_working_days", "admin_override_required")
    decision_url = f"{base}/feasibility-checks/{check['id']}/decision"
    assert client.put(decision_url, json={"decision": "approved", "reason": "ok"}, headers=admin).status_code == 200
    assert client.post(f"{base}/readiness", headers=a).json()["status"] == "ready"

    # Tuesday morning: the same date is now same day -> the old result no longer counts.
    CLOCK["now"] = datetime(2026, 9, 29, 9, 0, tzinfo=JDK_TIMEZONE)
    assert client.get(f"{base}/feasibility-checks/{check['id']}", headers=a).json()["is_current"] is False
    readiness = client.post(f"{base}/readiness", headers=a).json()
    assert (readiness["status"], readiness["reason_codes"]) == ("operational_assessment_required", ["feasibility_stale"])
    assert client.get(f"{base}/same-day-fg", headers=a).json()["decision"] == "admin_override_required"
    assert client.put(decision_url, json={"decision": "rejected", "reason": "late"}, headers=admin).status_code == 409

    # A fresh check is calculated for the new window.
    assert client.post(f"{base}/feasibility-checks", headers=a).json()["delivery_window"] == "same_day"
