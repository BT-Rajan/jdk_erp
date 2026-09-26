"""Sales S12: quotation acceptance, rejection, 7-day validity with
owner renewal, and Admin-only editing after a decision (S12.1)."""

from datetime import datetime
from decimal import Decimal

import pytest

from app.api import quotations as quotations_api
from app.core.roles import ADMIN, MANAGER, TEAM_MEMBER
from app.core.security import hash_password
from app.core.timezone import JDK_TIMEZONE
from app.models.audit_event import QUOTATION_ACCEPTED, QUOTATION_REJECTED, QUOTATION_RENEWED, AuditEvent
from app.models.customer import Customer
from app.models.team import Team
from app.models.user import User
from app.models.user_team import UserTeam
from app.services import feasibility_record_service, quotation_readiness_service, working_calendar_service

CLOCK = {"now": datetime(2026, 9, 28, 9, 0, tzinfo=JDK_TIMEZONE)}  # Monday 28 Sep, Kuwait


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
        "admin": _user(db_session, organisation, "boss", ADMIN),
    }
    db_session.add_all([UserTeam(user_id=users[k].id, team_id=team.id) for k in ("head", "a")])
    customer = Customer(organisation_id=organisation.id, code="300001", name="A Co", assigned_to_user_id=users["a"].id)
    db_session.add(customer)
    widget_product.min_selling_price = Decimal("90")
    widget_product.max_selling_price = Decimal("110")
    db_session.commit()
    return users, customer, widget_product


def _line(product, quantity="1", price="100"):
    return {"product_id": product.id, "quantity": quantity, "unit_of_measure_id": product.unit_of_measure_id, "unit_price": price}


def _quote(client, customer, product, **line):
    body = {"customer_id": customer.id, "requested_delivery_date": "2026-10-05", "lines": [_line(product, **line)]}
    response = client.post("/api/quotations", json=body, headers=_headers(client, "salesman_a"))
    assert response.status_code == 201, response.json()
    return response.json()


def test_owner_accepts_without_readiness_prerequisites(client, db_session, setup):
    users, customer, widget = setup
    quotation = _quote(client, customer, widget, price="150")  # price needs approval: not ready
    assert quotation["valid_until"] == "2026-10-05"
    url = f"/api/quotations/{quotation['id']}"

    for username in ("head", "boss"):
        assert client.get(url, headers=_headers(client, username)).json()["can_accept"] is False
        assert client.post(f"{url}/accept", headers=_headers(client, username)).status_code == 403
    assert client.get(url, headers=_headers(client, "salesman_a")).json()["can_accept"] is True

    accepted = client.post(f"{url}/accept", headers=_headers(client, "salesman_a")).json()
    assert (accepted["status"], accepted["order_eligible"], accepted["accepted_by_user_id"]) == ("accepted", True, users["a"].id)
    assert client.post(f"{url}/accept", headers=_headers(client, "salesman_a")).status_code == 409
    assert db_session.query(AuditEvent).filter(AuditEvent.action == QUOTATION_ACCEPTED).count() == 1


def test_owner_or_team_head_rejects_with_a_reason(client, db_session, setup):
    users, customer, widget = setup
    first, second = _quote(client, customer, widget), _quote(client, customer, widget)

    assert client.post(f"/api/quotations/{first['id']}/reject", json={"reason": " "}, headers=_headers(client, "salesman_a")).status_code == 422
    assert client.post(f"/api/quotations/{first['id']}/reject", json={"reason": "No"}, headers=_headers(client, "boss")).status_code == 403
    rejected = client.post(f"/api/quotations/{first['id']}/reject", json={"reason": "Price too high"}, headers=_headers(client, "head")).json()
    assert (rejected["status"], rejected["rejection_reason"], rejected["rejected_by_user_id"]) == ("rejected", "Price too high", users["head"].id)
    assert client.post(f"/api/quotations/{second['id']}/reject", json={"reason": "Lost"}, headers=_headers(client, "salesman_a")).status_code == 200

    # A rejection is final.
    assert client.post(f"/api/quotations/{first['id']}/accept", headers=_headers(client, "salesman_a")).status_code == 409
    assert db_session.query(AuditEvent).filter(AuditEvent.action == QUOTATION_REJECTED).count() == 2


def test_expired_quotation_needs_owner_renewal_before_acceptance(client, db_session, setup):
    users, customer, widget = setup
    quotation = _quote(client, customer, widget)  # quotation date 28 Sep -> valid until 5 Oct
    url = f"/api/quotations/{quotation['id']}"

    CLOCK["now"] = datetime(2026, 10, 5, 23, 0, tzinfo=JDK_TIMEZONE)  # last valid day
    assert client.get(url, headers=_headers(client, "salesman_a")).json()["is_expired"] is False
    assert client.post(f"{url}/renew", headers=_headers(client, "salesman_a")).status_code == 409

    CLOCK["now"] = datetime(2026, 10, 6, 9, 0, tzinfo=JDK_TIMEZONE)
    row = client.get(url, headers=_headers(client, "salesman_a")).json()
    assert (row["is_expired"], row["can_accept"], row["can_renew"]) == (True, False, True)
    assert client.post(f"{url}/accept", headers=_headers(client, "salesman_a")).status_code == 409
    assert client.post(f"{url}/renew", headers=_headers(client, "head")).status_code == 403

    renewed = client.post(f"{url}/renew", headers=_headers(client, "salesman_a")).json()
    assert (renewed["valid_until"], renewed["is_expired"]) == ("2026-10-13", False)
    assert client.post(f"{url}/accept", headers=_headers(client, "salesman_a")).json()["status"] == "accepted"
    assert db_session.query(AuditEvent).filter(AuditEvent.action == QUOTATION_RENEWED).count() == 1


def test_only_admin_edits_after_a_decision(client, setup):
    users, customer, widget = setup
    quotation = _quote(client, customer, widget)
    url = f"/api/quotations/{quotation['id']}"
    client.post(f"{url}/accept", headers=_headers(client, "salesman_a"))

    edit = {"lines": [_line(widget, quantity="2")]}
    assert client.get(url, headers=_headers(client, "salesman_a")).json()["can_edit"] is False
    assert client.patch(url, json=edit, headers=_headers(client, "salesman_a")).status_code == 403
    assert client.patch(url, json=edit, headers=_headers(client, "head")).status_code == 403
    assert client.get(url, headers=_headers(client, "boss")).json()["can_edit"] is True
    edited = client.patch(url, json=edit, headers=_headers(client, "boss")).json()
    assert (edited["status"], Decimal(edited["total_amount"])) == ("accepted", Decimal("200.000"))
