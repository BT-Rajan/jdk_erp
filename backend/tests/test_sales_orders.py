"""Sales S13/S14.2: Sales Orders -- manual conversion by the owning
salesman from an accepted quotation (which becomes converted and locked),
automatic hand-off to fulfilment on creation behind the S14.2
prerequisites, Admin-only cancellation and changes with a reason (changes
audited old -> new), customer-scoped access."""

from datetime import datetime
from decimal import Decimal

import pytest

from app.api import quotations as quotations_api
from app.api import sales_orders as sales_orders_api
from app.core.roles import ADMIN, MANAGER, TEAM_MEMBER
from app.core.security import hash_password
from app.core.timezone import JDK_TIMEZONE
from app.models.audit_event import (
    QUOTATION_CONVERTED,
    SALES_ORDER_CANCELLED,
    SALES_ORDER_CREATED,
    SALES_ORDER_UPDATED,
    QUOTATION_READINESS_ASSESSED,
    SALES_ORDER_HANDED_OFF,
    AuditEvent,
)
from app.models.customer import Customer
from app.models.feasibility_check import FeasibilityCheck
from app.models.sales_order import SalesOrder
from app.models.team import Team
from app.models.user import User
from app.models.user_team import UserTeam
from app.services import feasibility_record_service, quotation_readiness_service, working_calendar_service

MONDAY_9AM_KUWAIT = datetime(2026, 9, 28, 9, 0, tzinfo=JDK_TIMEZONE)


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
    for module in (working_calendar_service, quotations_api, sales_orders_api, feasibility_record_service, quotation_readiness_service):
        monkeypatch.setattr(module, "now_jdk", lambda: MONDAY_9AM_KUWAIT)
    team = Team(organisation_id=organisation.id, name="Sales", code="SALES", is_active=True)
    db_session.add(team)
    db_session.commit()
    users = {
        "head": _user(db_session, organisation, "head", MANAGER),
        "a": _user(db_session, organisation, "salesman_a", TEAM_MEMBER),
        "b": _user(db_session, organisation, "salesman_b", TEAM_MEMBER),
        "admin": _user(db_session, organisation, "boss", ADMIN),
    }
    db_session.add_all([UserTeam(user_id=users[k].id, team_id=team.id) for k in ("head", "a")])
    customer = Customer(
        organisation_id=organisation.id, code="300001", name="A Co", assigned_to_user_id=users["a"].id,
        phone="96511111111", address="Shuwaikh, Kuwait", payment_arrangement="after_delivery",
    )
    db_session.add(customer)
    widget_product.min_selling_price = Decimal("90")
    widget_product.max_selling_price = Decimal("110")
    db_session.commit()
    return users, customer, widget_product


def _line(product, quantity="3", price="100"):
    return {"product_id": product.id, "quantity": quantity, "unit_of_measure_id": product.unit_of_measure_id, "unit_price": price}


def _accepted_quotation(client, customer, product, requested="2026-10-05", price="100"):
    a = _headers(client, "salesman_a")
    body = {"customer_id": customer.id, "requested_delivery_date": requested, "lines": [_line(product, price=price)]}
    quotation = client.post("/api/quotations", json=body, headers=a).json()
    assert client.post(f"/api/quotations/{quotation['id']}/accept", headers=a).status_code == 200
    return quotation


def _convert(client, quotation_id, username="salesman_a"):
    return client.post(f"/api/quotations/{quotation_id}/convert", headers=_headers(client, username))


def test_owner_converts_an_accepted_quotation_which_is_then_locked(client, db_session, setup):
    users, customer, widget = setup
    a, admin = _headers(client, "salesman_a"), _headers(client, "boss")
    draft = client.post("/api/quotations", json={"customer_id": customer.id, "lines": [_line(widget)]}, headers=a).json()
    assert _convert(client, draft["id"]).status_code == 409  # not accepted

    quotation = _accepted_quotation(client, customer, widget)
    for username in ("head", "boss"):
        assert _convert(client, quotation["id"], username).status_code == 403
    assert client.get(f"/api/quotations/{quotation['id']}", headers=a).json()["can_convert"] is True

    response = _convert(client, quotation["id"])
    assert response.status_code == 201
    order = response.json()
    assert order["order_number"].startswith("266") and order["status"] == "handed_off"
    # Handed off automatically, triggered by the creating salesman.
    assert (order["handoff_source"], order["handed_off_by_user_id"]) == ("automatic", users["a"].id)
    assert order["handed_off_at"] is not None
    assert (order["quotation_id"], order["customer_id"], order["requested_delivery_date"]) == (quotation["id"], customer.id, "2026-10-05")
    assert [(l["product_id"], Decimal(l["quantity"]), Decimal(l["unit_price"])) for l in order["lines"]] == [(widget.id, Decimal("3"), Decimal("100"))]
    assert Decimal(order["total_amount"]) == Decimal(quotation["total_amount"]) == Decimal("300")

    converted = client.get(f"/api/quotations/{quotation['id']}", headers=a).json()
    assert (converted["status"], converted["sales_order_id"], converted["can_edit"]) == ("converted", order["id"], False)
    assert _convert(client, quotation["id"]).status_code == 409
    # Locked for everyone, Admin included.
    assert client.patch(f"/api/quotations/{quotation['id']}", json={"lines": [_line(widget, "1")]}, headers=admin).status_code == 409
    assert client.post(f"/api/quotations/{quotation['id']}/reject", json={"reason": "x"}, headers=a).status_code == 409
    for action in (QUOTATION_CONVERTED, SALES_ORDER_CREATED, SALES_ORDER_HANDED_OFF):
        assert db_session.query(AuditEvent).filter(AuditEvent.action == action).count() == 1
    handoff = db_session.query(AuditEvent).filter(AuditEvent.action == SALES_ORDER_HANDED_OFF).one()
    assert handoff.actor_user_id == users["a"].id and "source: automatic" in handoff.details


def test_after_handoff_only_admin_cancels_with_a_reason(client, db_session, setup):
    users, customer, widget = setup
    order = _convert(client, _accepted_quotation(client, customer, widget)["id"]).json()
    assert order["can_cancel"] is False  # the owning salesman

    url = f"/api/sales-orders/{order['id']}/cancel"
    for username in ("salesman_a", "head"):
        assert client.post(url, json={"reason": "Customer withdrew"}, headers=_headers(client, username)).status_code == 403
    admin = _headers(client, "boss")
    assert client.post(url, json={"reason": " "}, headers=admin).status_code == 422
    assert client.post(url, json={}, headers=admin).status_code == 422
    cancelled = client.post(url, json={"reason": "Customer withdrew"}, headers=admin).json()
    assert (cancelled["status"], cancelled["cancellation_reason"], cancelled["cancelled_by_user_id"]) == ("cancelled", "Customer withdrew", users["admin"].id)
    assert client.post(url, json={"reason": "Again"}, headers=admin).status_code == 409
    event = db_session.query(AuditEvent).filter(AuditEvent.action == SALES_ORDER_CANCELLED).one()
    assert event.actor_user_id == users["admin"].id and "Customer withdrew" in event.details


def test_after_handoff_admin_changes_date_quantity_and_price_with_history(client, db_session, setup):
    users, customer, widget = setup
    order = _convert(client, _accepted_quotation(client, customer, widget)["id"]).json()
    url = f"/api/sales-orders/{order['id']}"
    change = {"reason": "Customer asked for 5 a day later", "requested_delivery_date": "2026-10-06", "lines": [_line(widget, "5", "95")]}

    assert client.patch(url, json=change, headers=_headers(client, "salesman_a")).status_code == 403
    assert client.patch(url, json=change, headers=_headers(client, "head")).status_code == 403
    admin = _headers(client, "boss")
    assert client.patch(url, json={**change, "reason": " "}, headers=admin).status_code == 422
    assert client.patch(url, json={k: v for k, v in change.items() if k != "reason"}, headers=admin).status_code == 422
    other_unit = {**_line(widget, "5", "95"), "unit_of_measure_id": widget.unit_of_measure_id + 1}
    assert client.patch(url, json={**change, "lines": [other_unit]}, headers=admin).status_code == 422  # units fixed
    assert client.patch(url, json={**change, "lines": [_line(widget), _line(widget)]}, headers=admin).status_code == 422
    assert db_session.query(AuditEvent).filter(AuditEvent.action == SALES_ORDER_UPDATED).count() == 0

    changed = client.patch(url, json={**change, "order_number": "2669999", "total_amount": "1", "status": "cancelled"}, headers=admin).json()
    assert (changed["order_number"], changed["status"], changed["requested_delivery_date"]) == (order["order_number"], "handed_off", "2026-10-06")
    assert Decimal(changed["total_amount"]) == Decimal("475")

    event = db_session.query(AuditEvent).filter(AuditEvent.action == SALES_ORDER_UPDATED).one()
    assert event.actor_user_id == users["admin"].id and event.created_at is not None
    for fragment in (
        "requested_delivery_date: 2026-10-05 -> 2026-10-06",
        "line 1 quantity: 3 -> 5",
        "line 1 unit_price: 100 -> 95",
        "total_amount: 300 -> 475",
        "reason: Customer asked for 5 a day later",
    ):
        assert fragment in event.details

    client.post(f"{url}/cancel", json={"reason": "Lost"}, headers=admin)
    assert client.patch(url, json=change, headers=admin).status_code == 409


def test_orders_follow_customer_scope(client, setup):
    users, customer, widget = setup
    order = _convert(client, _accepted_quotation(client, customer, widget)["id"]).json()

    b = _headers(client, "salesman_b")
    assert client.get(f"/api/sales-orders/{order['id']}", headers=b).status_code == 404
    assert client.get("/api/sales-orders", headers=b).json()["data"] == []
    assert client.post(f"/api/sales-orders/{order['id']}/cancel", json={"reason": "x"}, headers=b).status_code == 404
    head_rows = client.get("/api/sales-orders", headers=_headers(client, "head")).json()["data"]
    assert [row["id"] for row in head_rows] == [order["id"]] and head_rows[0]["can_cancel"] is False


# --- S13.5 integrity fixes ---------------------------------------------------


def test_the_order_customer_can_never_change(client, db_session, organisation, setup):
    users, customer, widget = setup
    other = Customer(organisation_id=organisation.id, code="300002", name="B Co", assigned_to_user_id=users["a"].id)
    db_session.add(other)
    db_session.commit()
    order = _convert(client, _accepted_quotation(client, customer, widget)["id"]).json()
    url, admin = f"/api/sales-orders/{order['id']}", _headers(client, "boss")

    response = client.patch(url, json={"reason": "Wrong customer", "customer_id": other.id}, headers=admin)
    assert response.status_code == 422 and "customer_id" in response.json()["error"]["fields"]
    assert client.get(url, headers=admin).json()["customer_id"] == customer.id
    assert db_session.query(AuditEvent).filter(AuditEvent.action == SALES_ORDER_UPDATED).count() == 0
    # Naming the same customer is not a change; other Admin edits still work.
    same = client.patch(url, json={"reason": "Qty", "customer_id": customer.id, "lines": [_line(widget, "4")]}, headers=admin)
    assert same.status_code == 200 and same.json()["customer_id"] == customer.id


def test_a_converted_quotation_locks_feasibility_and_readiness(client, db_session, setup):
    users, customer, widget = setup
    a, admin = _headers(client, "salesman_a"), _headers(client, "boss")
    quotation = _accepted_quotation(client, customer, widget, requested="2026-10-02")  # Friday: needs Admin
    base = f"/api/quotations/{quotation['id']}"

    # Not converted yet: feasibility and readiness behave as before.
    check = client.post(f"{base}/feasibility-checks", headers=a)
    assert check.status_code == 201 and check.json()["state"] == "admin_override_required"
    decision_url = f"{base}/feasibility-checks/{check.json()['id']}/decision"
    assert client.put(decision_url, json={"decision": "approved", "reason": "OK"}, headers=admin).status_code == 200
    assert client.post(f"{base}/readiness", headers=a).status_code == 200
    audits = db_session.query(AuditEvent).filter(AuditEvent.action == QUOTATION_READINESS_ASSESSED).count()

    assert _convert(client, quotation["id"]).status_code == 201
    assert client.post(f"{base}/feasibility-checks", headers=a).status_code == 409
    assert client.put(decision_url, json={"decision": "rejected", "reason": "No"}, headers=admin).status_code == 409
    assert client.post(f"{base}/readiness", headers=a).status_code == 409
    assert db_session.query(FeasibilityCheck).count() == 1
    assert client.get(f"{base}/feasibility-checks", headers=a).json()[0]["state"] == "approved"
    assert db_session.query(AuditEvent).filter(AuditEvent.action == QUOTATION_READINESS_ASSESSED).count() == audits



# --- S14.2 hand-off prerequisites ---------------------------------------------


def test_handoff_needs_customer_phone_address_and_payment_arrangement(client, db_session, setup):
    users, customer, widget = setup
    admin = _headers(client, "boss")
    quotation = _accepted_quotation(client, customer, widget)
    for field, value in (("phone", None), ("address", " "), ("payment_arrangement", None)):
        saved = getattr(customer, field)
        setattr(customer, field, value)
        db_session.commit()
        response = _convert(client, quotation["id"])
        assert response.status_code == 422 and field in response.json()["error"]["fields"]
        setattr(customer, field, saved)
        db_session.commit()
    assert db_session.query(SalesOrder).count() == 0

    # Admin sets the arrangement through the customer record; a plan needs its terms.
    customer_url = f"/api/customers/{customer.id}"
    assert client.patch(customer_url, json={"payment_arrangement": "payment_plan"}, headers=admin).status_code == 422
    plan = {"payment_arrangement": "payment_plan", "payment_plan_details": "50% on order, 50% on delivery"}
    assert client.patch(customer_url, json=plan, headers=_headers(client, "salesman_a")).status_code == 403
    assert client.patch(customer_url, json=plan, headers=admin).json()["payment_arrangement"] == "payment_plan"
    # An arrangement is enough -- nothing has been paid.
    order = _convert(client, quotation["id"])
    assert order.status_code == 201 and order.json()["status"] == "handed_off"


def test_handoff_refuses_a_past_date_by_kuwait_date(client, db_session, setup, monkeypatch):
    users, customer, widget = setup
    quotation = _accepted_quotation(client, customer, widget, requested="2026-10-05")
    # 00:30 on 6 Oct in Kuwait is still 5 Oct in UTC: Kuwait's date decides.
    late = datetime(2026, 10, 6, 0, 30, tzinfo=JDK_TIMEZONE)
    for module in (quotations_api, working_calendar_service, feasibility_record_service, quotation_readiness_service):
        monkeypatch.setattr(module, "now_jdk", lambda: late)
    response = _convert(client, quotation["id"])
    assert response.status_code == 409 and "requested_date_passed" in response.json()["error"]["message"]
    assert db_session.query(SalesOrder).count() == 0
    assert client.get(f"/api/quotations/{quotation['id']}", headers=_headers(client, "salesman_a")).json()["status"] == "accepted"


def test_handoff_needs_prices_in_range_or_admin_approved(client, db_session, setup):
    users, customer, widget = setup
    quotation = _accepted_quotation(client, customer, widget, price="120")  # permitted 90-110
    response = _convert(client, quotation["id"])
    assert response.status_code == 409 and "price_outside_range" in response.json()["error"]["message"]

    decision = {"decision": "approved", "reason": "Premium delivery"}
    assert client.put(f"/api/quotations/{quotation['id']}/price-decision", json=decision, headers=_headers(client, "boss")).status_code == 200
    order = _convert(client, quotation["id"])
    assert order.status_code == 201 and Decimal(order.json()["lines"][0]["unit_price"]) == Decimal("120")


def test_handoff_needs_current_acceptable_feasibility(client, db_session, setup):
    users, customer, widget = setup
    a, admin = _headers(client, "salesman_a"), _headers(client, "boss")
    quotation = _accepted_quotation(client, customer, widget, requested="2026-09-30")  # within 2 working days
    base = f"/api/quotations/{quotation['id']}"

    def refused(code):
        response = _convert(client, quotation["id"])
        assert response.status_code == 409 and code in response.json()["error"]["message"]

    refused("feasibility_required")
    check = client.post(f"{base}/feasibility-checks", headers=a).json()  # no BOM -> needs Admin
    assert check["state"] == "admin_override_required"
    refused("admin_override_required")
    approve = {"decision": "approved", "reason": "Can deliver"}
    assert client.put(f"{base}/feasibility-checks/{check['id']}/decision", json=approve, headers=admin).status_code == 200
    # Admin changes the quantity afterwards: the approved result is stale.
    assert client.patch(base, json={"lines": [_line(widget, "4")]}, headers=admin).status_code == 200
    refused("feasibility_stale")
    assert db_session.query(SalesOrder).count() == 0

    check = client.post(f"{base}/feasibility-checks", headers=a).json()
    assert client.put(f"{base}/feasibility-checks/{check['id']}/decision", json=approve, headers=admin).status_code == 200
    assert _convert(client, quotation["id"]).status_code == 201
