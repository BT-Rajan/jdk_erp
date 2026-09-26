"""Sales S11.1: the two Admin dead ends now have an explicit, audited,
Admin-only decision (prices; non-working requested dates via S8), and
readiness in the normal flow always goes through the audited POST."""

from datetime import date, datetime
from decimal import Decimal

import pytest

from app.api import quotations as quotations_api
from app.core.roles import ADMIN, MANAGER, TEAM_MEMBER
from app.core.security import hash_password
from app.core.timezone import JDK_TIMEZONE
from app.models.audit_event import QUOTATION_PRICE_DECIDED, QUOTATION_READINESS_ASSESSED, AuditEvent
from app.models.customer import Customer
from app.models.team import Team
from app.models.user import User
from app.models.user_team import UserTeam
from app.services import feasibility_record_service, quotation_readiness_service, working_calendar_service

MONDAY_9AM_KUWAIT = datetime(2026, 9, 28, 9, 0, tzinfo=JDK_TIMEZONE)
NEXT_MONDAY = date(2026, 10, 5)  # more than 2 working days: no feasibility needed
FRIDAY = date(2026, 10, 2)


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
    """Clock fixed at Monday 09:00 Kuwait; Widget permitted price 90-110."""
    for module in (working_calendar_service, quotations_api, feasibility_record_service, quotation_readiness_service):
        monkeypatch.setattr(module, "now_jdk", lambda: MONDAY_9AM_KUWAIT)
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


def _quote(client, customer, product, requested, price="100", quantity="1"):
    body = {
        "customer_id": customer.id,
        "requested_delivery_date": requested.isoformat(),
        "lines": [{"product_id": product.id, "quantity": quantity, "unit_of_measure_id": product.unit_of_measure_id, "unit_price": price}],
    }
    response = client.post("/api/quotations", json=body, headers=_headers(client, "salesman_a"))
    assert response.status_code == 201, response.json()
    return response.json()["id"]


def _readiness(client, quotation_id):
    body = client.post(f"/api/quotations/{quotation_id}/readiness", headers=_headers(client, "salesman_a")).json()
    return body["status"], body["reason_codes"]


def test_admin_price_decision_unblocks_or_keeps_blocked(client, db_session, setup):
    users, customer, widget = setup
    quotation_id = _quote(client, customer, widget, NEXT_MONDAY, price="120")
    url = f"/api/quotations/{quotation_id}/price-decision"
    assert _readiness(client, quotation_id) == ("commercial_approval_required", ["price_outside_range"])

    for username in ("salesman_a", "head"):
        assert client.put(url, json={"decision": "approved", "reason": "ok"}, headers=_headers(client, username)).status_code == 403
    admin = _headers(client, "boss")
    assert client.put(url, json={"decision": "approved", "reason": " "}, headers=admin).status_code == 422

    approved = client.put(url, json={"decision": "approved", "reason": "Volume customer"}, headers=admin).json()
    assert (approved["price_decision"], approved["readiness_status"]) == ("approved", "ready")
    client.put(url, json={"decision": "rejected", "reason": "Margin too low"}, headers=admin)
    assert _readiness(client, quotation_id) == ("commercial_approval_required", ["price_approval_rejected"])
    assert db_session.query(AuditEvent).filter(AuditEvent.action == QUOTATION_PRICE_DECIDED).count() == 2

    # New prices need a new decision.
    client.patch(
        f"/api/quotations/{quotation_id}",
        json={"lines": [{"product_id": widget.id, "quantity": "1", "unit_of_measure_id": widget.unit_of_measure_id, "unit_price": "125"}]},
        headers=_headers(client, "salesman_a"),
    )
    assert _readiness(client, quotation_id) == ("commercial_approval_required", ["price_outside_range"])

    # Nothing to decide when every price is within range.
    in_range = _quote(client, customer, widget, NEXT_MONDAY)
    assert client.put(f"/api/quotations/{in_range}/price-decision", json={"decision": "approved", "reason": "x"}, headers=admin).status_code == 409


def test_non_working_date_goes_to_an_admin_decision(client, setup):
    users, customer, widget = setup
    quotation_id = _quote(client, customer, widget, FRIDAY)
    base = f"/api/quotations/{quotation_id}"
    check = client.post(f"{base}/feasibility-checks", headers=_headers(client, "salesman_a")).json()
    assert (check["state"], check["result"]) == ("admin_override_required", "not_servable")
    assert _readiness(client, quotation_id) == ("admin_override_required", ["requested_date_non_working"])

    url = f"{base}/feasibility-checks/{check['id']}/decision"
    assert client.put(url, json={"decision": "approved", "reason": "ok"}, headers=_headers(client, "salesman_a")).status_code == 403
    admin = _headers(client, "boss")
    assert client.put(url, json={"decision": "approved", "reason": "Customer collects Friday"}, headers=admin).status_code == 200
    assert _readiness(client, quotation_id) == ("ready", [])
    assert client.put(url, json={"decision": "rejected", "reason": "No Friday staff"}, headers=admin).status_code == 200
    assert _readiness(client, quotation_id) == ("not_servable", ["feasibility_rejected"])
    # The requested date itself is never changed.
    assert client.get(base, headers=_headers(client, "salesman_a")).json()["requested_delivery_date"] == FRIDAY.isoformat()


def test_readiness_in_the_normal_flow_is_always_audited(client, db_session, setup):
    users, customer, widget = setup
    quotation_id = _quote(client, customer, widget, NEXT_MONDAY)
    headers = _headers(client, "salesman_a")

    assert client.get(f"/api/quotations/{quotation_id}/readiness", headers=headers).status_code == 405
    assert client.post(f"/api/quotations/{quotation_id}/readiness", headers=headers).json()["status"] == "ready"
    event = db_session.query(AuditEvent).filter(AuditEvent.action == QUOTATION_READINESS_ASSESSED).one()
    assert event.entity_id == quotation_id and event.actor_user_id == users["a"].id
