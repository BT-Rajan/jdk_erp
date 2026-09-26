"""Delivery D4: Delivery Instruction states -- pending -> fulfilled (final),
pending -> not_fulfilled (reason) -> pending (retry). Fulfilment is checked
against the order line's cumulative permitted quantity (fulfilled
instructions only), and repeated requests never apply twice."""

from datetime import datetime
from decimal import Decimal

import pytest

from app.api import quotations as quotations_api
from app.api import sales_orders as sales_orders_api
from app.core.roles import ADMIN, TEAM_MEMBER
from app.core.security import hash_password
from app.core.timezone import JDK_TIMEZONE
from app.models.audit_event import DELIVERY_FULFILLED, DELIVERY_NOT_FULFILLED, DELIVERY_RETRIED, AuditEvent
from app.models.customer import Customer
from app.models.role_permission import RolePermission
from app.models.user import User
from app.services import (
    feasibility_record_service,
    finished_goods_inventory_service,
    quotation_readiness_service,
    working_calendar_service,
)

MONDAY_9AM_KUWAIT = datetime(2026, 9, 28, 9, 0, tzinfo=JDK_TIMEZONE)


def _user(db_session, organisation, username, role):
    db_session.add(User(
        organisation_id=organisation.id, role=role, full_name=username.title(), email=f"{username}@example.com",
        username=username, password_hash=hash_password("Str0ng!Pass"), is_active=True,
    ))
    db_session.commit()


def _headers(client, username):
    login = client.post("/api/auth/login", json={"username": username, "password": "Str0ng!Pass"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.fixture()
def setup(client, db_session, organisation, widget_product, warehouse_1, monkeypatch):
    """A handed-off order for 100 Widgets; allowance 2% (ceiling 102);
    200 Widgets in finished goods stock (fulfilment issues stock, D5)."""
    for module in (working_calendar_service, quotations_api, sales_orders_api, feasibility_record_service, quotation_readiness_service):
        monkeypatch.setattr(module, "now_jdk", lambda: MONDAY_9AM_KUWAIT)
    monkeypatch.setattr("app.api.delivery_instructions.now_jdk", lambda: MONDAY_9AM_KUWAIT)
    for username, role in (("salesman_a", TEAM_MEMBER), ("warehouse", "manager"), ("boss", ADMIN)):
        _user(db_session, organisation, username, role)
    db_session.add(RolePermission(organisation_id=organisation.id, role="manager", module_key="inventory", action="deliver", scope="all"))
    salesman = db_session.query(User).filter(User.username == "salesman_a").one()
    customer = Customer(
        organisation_id=organisation.id, code="300001", name="A Co", assigned_to_user_id=salesman.id,
        phone="96511111111", address="Shuwaikh", payment_arrangement="after_delivery",
    )
    widget_product.min_selling_price, widget_product.max_selling_price = Decimal("90"), Decimal("110")
    db_session.add(customer)
    db_session.commit()
    finished_goods_inventory_service.receive_finished_goods(
        db_session, organisation_id=organisation.id, product_id=widget_product.id, warehouse_id=warehouse_1.id,
        quantity=Decimal("200"), unit_of_measure_id=widget_product.unit_of_measure_id, reference_type="test_seed",
        reference_id=1, created_by_user_id=None,
    )
    db_session.commit()
    client.patch("/api/organisations/me", json={"delivery_scrap_allowance_percent": "2"}, headers=_headers(client, "boss"))
    a = _headers(client, "salesman_a")
    line = {"product_id": widget_product.id, "quantity": "100", "unit_of_measure_id": widget_product.unit_of_measure_id, "unit_price": "100"}
    quotation = client.post("/api/quotations", json={"customer_id": customer.id, "requested_delivery_date": "2026-10-05", "lines": [line]}, headers=a).json()
    client.post(f"/api/quotations/{quotation['id']}/accept", headers=a)
    return client.post(f"/api/quotations/{quotation['id']}/convert", headers=a).json()


def _create(client, order, quantity):
    body = {"sales_order_id": order["id"], "lines": [{"sales_order_line_id": order["lines"][0]["id"], "quantity": quantity}]}
    response = client.post("/api/delivery-instructions", json=body, headers=_headers(client, "warehouse"))
    assert response.status_code == 201
    instruction = response.json()
    # Pallets are required for a non-mass product before anything else is recorded.
    client.patch(
        f"/api/delivery-instructions/{instruction['id']}/lines/{instruction['lines'][0]['id']}",
        json={"pallet_count": 1},
        headers=_headers(client, "warehouse"),
    )
    return instruction


def _post(client, instruction, action, body=None, username="warehouse"):
    return client.post(f"/api/delivery-instructions/{instruction['id']}/{action}", json=body, headers=_headers(client, username))


def _fulfilled_quantity(client, order):
    position = client.get(f"/api/delivery-instructions/position?sales_order_id={order['id']}", headers=_headers(client, "warehouse")).json()
    return Decimal(position["lines"][0]["fulfilled_quantity"])


def _count(db_session, action):
    return db_session.query(AuditEvent).filter(AuditEvent.action == action).count()


def test_pending_to_fulfilled_is_final_and_never_repeats(client, db_session, setup):
    order = setup
    instruction = _create(client, order, "40")
    assert instruction["status"] == "pending"

    fulfilled = _post(client, instruction, "fulfil")
    assert fulfilled.status_code == 200
    body = fulfilled.json()
    assert body["status"] == "fulfilled" and body["fulfilled_at"] and body["fulfilled_by_user_id"]
    assert _fulfilled_quantity(client, order) == Decimal("40")

    # Repeating, retrying or failing it afterwards is refused and changes nothing.
    for action, payload in (("fulfil", None), ("fulfil", None), ("retry", None), ("not-fulfilled", {"reason": "Truck broke down"})):
        response = _post(client, instruction, action, payload)
        assert response.status_code == 409, action
    assert "already been fulfilled" in _post(client, instruction, "fulfil").json()["error"]["message"]
    assert _count(db_session, DELIVERY_FULFILLED) == 1 and _count(db_session, DELIVERY_NOT_FULFILLED) == 0
    assert _fulfilled_quantity(client, order) == Decimal("40")
    # The fulfilled quantity is immutable.
    line_url = f"/api/delivery-instructions/{instruction['id']}/lines/{instruction['lines'][0]['id']}"
    assert client.patch(line_url, json={"quantity": "10"}, headers=_headers(client, "warehouse")).status_code == 409


def test_not_fulfilled_needs_a_reason_counts_for_nothing_and_can_be_retried(client, db_session, setup):
    order = setup
    instruction = _create(client, order, "40")
    assert _post(client, instruction, "not-fulfilled", {"reason": "  "}).status_code == 422
    assert _post(client, instruction, "not-fulfilled", {}).status_code == 422
    failed = _post(client, instruction, "not-fulfilled", {"reason": "Customer site closed"}).json()
    assert (failed["status"], failed["not_fulfilled_reason"]) == ("not_fulfilled", "Customer site closed")
    assert _fulfilled_quantity(client, order) == Decimal("0")
    assert _post(client, instruction, "fulfil").status_code == 409  # retry first

    retried = _post(client, instruction, "retry").json()
    assert (retried["status"], retried["not_fulfilled_reason"]) == ("pending", None)
    assert _post(client, instruction, "retry").status_code == 409
    # The quantity may be reviewed before the next attempt, then fulfilled.
    line_url = f"/api/delivery-instructions/{instruction['id']}/lines/{instruction['lines'][0]['id']}"
    assert client.patch(line_url, json={"quantity": "35"}, headers=_headers(client, "warehouse")).status_code == 200
    assert _post(client, instruction, "fulfil").json()["status"] == "fulfilled"
    assert _fulfilled_quantity(client, order) == Decimal("35")
    events = [e.details for e in db_session.query(AuditEvent).filter(AuditEvent.action.in_([DELIVERY_NOT_FULFILLED, DELIVERY_RETRIED])).order_by(AuditEvent.id)]
    assert "pending -> not_fulfilled; reason: Customer site closed" in events[0] and "not_fulfilled -> pending" in events[1]


def test_fulfilment_respects_the_cumulative_allowance(client, db_session, setup):
    order = setup
    for quantity in ("40", "40"):
        assert _post(client, _create(client, order, quantity), "fulfil").status_code == 200
    # 80 fulfilled, ceiling 102: 23 is refused, 22 fits.
    over = _create(client, order, "23")
    refused = _post(client, over, "fulfil")
    assert refused.status_code == 409 and "may still be delivered" in refused.json()["error"]["message"]
    assert _fulfilled_quantity(client, order) == Decimal("80")
    line_url = f"/api/delivery-instructions/{over['id']}/lines/{over['lines'][0]['id']}"
    assert client.patch(line_url, json={"quantity": "22"}, headers=_headers(client, "warehouse")).status_code == 200
    assert _post(client, over, "fulfil").status_code == 200
    assert _fulfilled_quantity(client, order) == Decimal("102")


def test_an_admin_override_recorded_on_the_line_allows_fulfilment_above_the_ceiling(client, setup):
    order = setup
    instruction = _create(client, order, "40")
    line_url = f"/api/delivery-instructions/{instruction['id']}/lines/{instruction['lines'][0]['id']}"
    client.patch(line_url, json={"quantity": "103", "override_reason": "Customer accepted the extra"}, headers=_headers(client, "boss"))
    assert _post(client, instruction, "fulfil").status_code == 200
    assert _fulfilled_quantity(client, order) == Decimal("103")
