"""Sales S13: Sales Orders per the S13.1 decisions -- manual conversion by
the owning salesman from an accepted quotation (which becomes converted
and locked), owner/head cancellation with a reason, Admin-only changes
with a reason, customer-scoped access."""

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
    AuditEvent,
)
from app.models.customer import Customer
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
    customer = Customer(organisation_id=organisation.id, code="300001", name="A Co", assigned_to_user_id=users["a"].id)
    db_session.add(customer)
    widget_product.min_selling_price = Decimal("90")
    widget_product.max_selling_price = Decimal("110")
    db_session.commit()
    return users, customer, widget_product


def _line(product, quantity="3", price="100"):
    return {"product_id": product.id, "quantity": quantity, "unit_of_measure_id": product.unit_of_measure_id, "unit_price": price}


def _accepted_quotation(client, customer, product):
    a = _headers(client, "salesman_a")
    body = {"customer_id": customer.id, "requested_delivery_date": "2026-10-05", "lines": [_line(product)]}
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
    assert order["order_number"].startswith("266") and order["status"] == "open"
    assert (order["quotation_id"], order["customer_id"], order["requested_delivery_date"]) == (quotation["id"], customer.id, "2026-10-05")
    assert [(l["product_id"], Decimal(l["quantity"]), Decimal(l["unit_price"])) for l in order["lines"]] == [(widget.id, Decimal("3"), Decimal("100"))]
    assert Decimal(order["total_amount"]) == Decimal(quotation["total_amount"]) == Decimal("300")

    converted = client.get(f"/api/quotations/{quotation['id']}", headers=a).json()
    assert (converted["status"], converted["sales_order_id"], converted["can_edit"]) == ("converted", order["id"], False)
    assert _convert(client, quotation["id"]).status_code == 409
    # Locked for everyone, Admin included.
    assert client.patch(f"/api/quotations/{quotation['id']}", json={"lines": [_line(widget, "1")]}, headers=admin).status_code == 409
    assert client.post(f"/api/quotations/{quotation['id']}/reject", json={"reason": "x"}, headers=a).status_code == 409
    for action in (QUOTATION_CONVERTED, SALES_ORDER_CREATED):
        assert db_session.query(AuditEvent).filter(AuditEvent.action == action).count() == 1


def test_owner_or_head_cancels_with_a_reason(client, db_session, setup):
    users, customer, widget = setup
    first = _convert(client, _accepted_quotation(client, customer, widget)["id"]).json()
    second = _convert(client, _accepted_quotation(client, customer, widget)["id"]).json()

    url = f"/api/sales-orders/{first['id']}/cancel"
    assert client.post(url, json={"reason": " "}, headers=_headers(client, "salesman_a")).status_code == 422
    assert client.post(url, json={"reason": "No"}, headers=_headers(client, "boss")).status_code == 403
    cancelled = client.post(url, json={"reason": "Customer withdrew"}, headers=_headers(client, "head")).json()
    assert (cancelled["status"], cancelled["cancellation_reason"], cancelled["cancelled_by_user_id"]) == ("cancelled", "Customer withdrew", users["head"].id)
    assert client.post(url, json={"reason": "Again"}, headers=_headers(client, "salesman_a")).status_code == 409
    assert client.post(f"/api/sales-orders/{second['id']}/cancel", json={"reason": "Lost"}, headers=_headers(client, "salesman_a")).status_code == 200
    assert db_session.query(AuditEvent).filter(AuditEvent.action == SALES_ORDER_CANCELLED).count() == 2


def test_only_admin_changes_an_open_order_with_a_reason(client, db_session, setup):
    users, customer, widget = setup
    order = _convert(client, _accepted_quotation(client, customer, widget)["id"]).json()
    url = f"/api/sales-orders/{order['id']}"
    change = {"reason": "Customer asked for 5", "lines": [_line(widget, "5", "95")]}

    assert client.patch(url, json=change, headers=_headers(client, "salesman_a")).status_code == 403
    assert client.patch(url, json={**change, "reason": " "}, headers=_headers(client, "boss")).status_code == 422
    changed = client.patch(url, json={**change, "order_number": "2669999", "total_amount": "1", "status": "cancelled"}, headers=_headers(client, "boss")).json()
    assert (changed["order_number"], changed["status"], Decimal(changed["total_amount"])) == (order["order_number"], "open", Decimal("475.000"))
    event = db_session.query(AuditEvent).filter(AuditEvent.action == SALES_ORDER_UPDATED).one()
    assert "Customer asked for 5" in event.details

    client.post(f"{url}/cancel", json={"reason": "Lost"}, headers=_headers(client, "salesman_a"))
    assert client.patch(url, json=change, headers=_headers(client, "boss")).status_code == 409


def test_orders_follow_customer_scope(client, setup):
    users, customer, widget = setup
    order = _convert(client, _accepted_quotation(client, customer, widget)["id"]).json()

    b = _headers(client, "salesman_b")
    assert client.get(f"/api/sales-orders/{order['id']}", headers=b).status_code == 404
    assert client.get("/api/sales-orders", headers=b).json()["data"] == []
    assert client.post(f"/api/sales-orders/{order['id']}/cancel", json={"reason": "x"}, headers=b).status_code == 404
    head_rows = client.get("/api/sales-orders", headers=_headers(client, "head")).json()["data"]
    assert [row["id"] for row in head_rows] == [order["id"]] and head_rows[0]["can_cancel"] is True
