"""Delivery D6: a Sales Order's delivery status follows its fulfilled
Delivery Instructions only -- handed_off -> partially_delivered ->
completed, per line (one product never counts for another), completed
once every line reaches its ordered quantity (the allowance is a ceiling,
not a target). Changed only by a successful fulfilment."""

from datetime import datetime
from decimal import Decimal

import pytest

from app.api import quotations as quotations_api
from app.api import sales_orders as sales_orders_api
from app.core.roles import ADMIN, TEAM_MEMBER
from app.core.security import hash_password
from app.core.timezone import JDK_TIMEZONE
from app.models.audit_event import SALES_ORDER_DELIVERY_STATUS, AuditEvent
from app.models.customer import Customer
from app.models.product import Product
from app.models.role_permission import RolePermission
from app.models.user import User
from app.services import (
    feasibility_record_service,
    finished_goods_inventory_service,
    quotation_readiness_service,
    working_calendar_service,
)

MONDAY_9AM_KUWAIT = datetime(2026, 9, 28, 9, 0, tzinfo=JDK_TIMEZONE)


def _headers(client, username):
    login = client.post("/api/auth/login", json={"username": username, "password": "Str0ng!Pass"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.fixture()
def setup(client, db_session, organisation, electronics_category, widget_product, warehouse_1, monkeypatch):
    """Order: 100 Widgets + 50 Gadgets; allowance 2%; plenty of stock."""
    for module in (working_calendar_service, quotations_api, sales_orders_api, feasibility_record_service, quotation_readiness_service):
        monkeypatch.setattr(module, "now_jdk", lambda: MONDAY_9AM_KUWAIT)
    monkeypatch.setattr("app.api.delivery_instructions.now_jdk", lambda: MONDAY_9AM_KUWAIT)
    for username, role in (("salesman_a", TEAM_MEMBER), ("warehouse", "manager"), ("boss", ADMIN)):
        db_session.add(User(
            organisation_id=organisation.id, role=role, full_name=username.title(), email=f"{username}@example.com",
            username=username, password_hash=hash_password("Str0ng!Pass"), is_active=True,
        ))
    db_session.add(RolePermission(organisation_id=organisation.id, role="manager", module_key="inventory", action="deliver", scope="all"))
    gadget = Product(
        organisation_id=organisation.id, code="GDG", name="Gadget", category_id=electronics_category.id,
        unit_of_measure_id=widget_product.unit_of_measure_id, selling_price=50,
        min_selling_price=Decimal("40"), max_selling_price=Decimal("60"), is_active=True,
    )
    widget_product.min_selling_price, widget_product.max_selling_price = Decimal("90"), Decimal("110")
    db_session.add(gadget)
    db_session.commit()
    salesman = db_session.query(User).filter(User.username == "salesman_a").one()
    customer = Customer(
        organisation_id=organisation.id, code="300001", name="A Co", assigned_to_user_id=salesman.id,
        phone="96511111111", address="Shuwaikh", payment_arrangement="after_delivery",
    )
    db_session.add(customer)
    db_session.commit()
    for product in (widget_product, gadget):
        finished_goods_inventory_service.receive_finished_goods(
            db_session, organisation_id=organisation.id, product_id=product.id, warehouse_id=warehouse_1.id,
            quantity=Decimal("500"), unit_of_measure_id=product.unit_of_measure_id, reference_type="test_seed",
            reference_id=product.id, created_by_user_id=None,
        )
    db_session.commit()
    client.patch("/api/organisations/me", json={"delivery_scrap_allowance_percent": "2"}, headers=_headers(client, "boss"))
    a = _headers(client, "salesman_a")
    lines = [
        {"product_id": widget_product.id, "quantity": "100", "unit_of_measure_id": widget_product.unit_of_measure_id, "unit_price": "100"},
        {"product_id": gadget.id, "quantity": "50", "unit_of_measure_id": gadget.unit_of_measure_id, "unit_price": "50"},
    ]
    quotation = client.post("/api/quotations", json={"customer_id": customer.id, "requested_delivery_date": "2026-10-05", "lines": lines}, headers=a).json()
    client.post(f"/api/quotations/{quotation['id']}/accept", headers=a)
    return client.post(f"/api/quotations/{quotation['id']}/convert", headers=a).json()


def _deliver(client, order, quantities, fulfil=True):
    wh = _headers(client, "warehouse")
    body = {"sales_order_id": order["id"], "lines": [
        {"sales_order_line_id": order["lines"][i]["id"], "quantity": q} for i, q in quantities.items()
    ]}
    instruction = client.post("/api/delivery-instructions", json=body, headers=wh).json()
    for line in instruction["lines"]:
        client.patch(f"/api/delivery-instructions/{instruction['id']}/lines/{line['id']}", json={"pallet_count": 1}, headers=wh)
    if fulfil:
        assert client.post(f"/api/delivery-instructions/{instruction['id']}/fulfil", headers=wh).status_code == 200
    return instruction


def _order(client, order):
    body = client.get(f"/api/sales-orders/{order['id']}", headers=_headers(client, "boss")).json()
    progress = [(Decimal(l["quantity"]), Decimal(l["fulfilled_quantity"]), Decimal(l["remaining_quantity"])) for l in body["lines"]]  # noqa: E741
    return body["status"], progress


def test_status_follows_fulfilled_tranches_per_line(client, db_session, setup):
    order = setup
    # Pending and not-fulfilled instructions change nothing.
    pending = _deliver(client, order, {0: "40"}, fulfil=False)
    failed = _deliver(client, order, {1: "10"}, fulfil=False)
    client.post(f"/api/delivery-instructions/{failed['id']}/not-fulfilled", json={"reason": "No truck"}, headers=_headers(client, "warehouse"))
    assert _order(client, order) == ("handed_off", [(100, 0, 100), (50, 0, 50)])

    client.post(f"/api/delivery-instructions/{pending['id']}/fulfil", headers=_headers(client, "warehouse"))
    assert _order(client, order) == ("partially_delivered", [(100, 40, 60), (50, 0, 50)])
    _deliver(client, order, {0: "30"})
    assert _order(client, order) == ("partially_delivered", [(100, 70, 30), (50, 0, 50)])
    # Widgets complete, Gadgets outstanding: 100 Widgets never satisfy the Gadget line.
    _deliver(client, order, {0: "30"})
    assert _order(client, order) == ("partially_delivered", [(100, 100, 0), (50, 0, 50)])
    _deliver(client, order, {1: "50"})
    assert _order(client, order) == ("completed", [(100, 100, 0), (50, 50, 0)])

    transitions = [e.details for e in db_session.query(AuditEvent).filter(AuditEvent.action == SALES_ORDER_DELIVERY_STATUS).order_by(AuditEvent.id)]
    assert len(transitions) == 2
    assert "handed_off -> partially_delivered; by delivery instruction" in transitions[0]
    assert "partially_delivered -> completed" in transitions[1]


def test_completion_within_the_allowance_and_no_double_counting(client, db_session, setup):
    order = setup
    first = _deliver(client, order, {0: "60", 1: "20"})
    # Repeating a fulfilment changes nothing.
    assert client.post(f"/api/delivery-instructions/{first['id']}/fulfil", headers=_headers(client, "warehouse")).status_code == 409
    assert _order(client, order) == ("partially_delivered", [(100, 60, 40), (50, 20, 30)])
    # 60 + 42 = 102 Widgets (the 2% ceiling) and 20 + 31 = 51 Gadgets: completed, with nothing "owed".
    _deliver(client, order, {0: "42", 1: "31"})
    status, progress = _order(client, order)
    assert status == "completed" and progress == [(100, 102, -2), (50, 51, -1)]
    assert db_session.query(AuditEvent).filter(AuditEvent.action == SALES_ORDER_DELIVERY_STATUS).count() == 2
    # Completed is final: no new instruction.
    body = {"sales_order_id": order["id"], "lines": [{"sales_order_line_id": order["lines"][0]["id"], "quantity": "1"}]}
    assert client.post("/api/delivery-instructions", json=body, headers=_headers(client, "warehouse")).status_code == 409


def test_cancellation_is_unchanged(client, setup):
    order = setup
    boss = _headers(client, "boss")
    _deliver(client, order, {0: "40"})
    # Only a handed-off order can be cancelled (existing rule); a partly delivered one cannot.
    assert client.post(f"/api/sales-orders/{order['id']}/cancel", json={"reason": "Lost"}, headers=boss).status_code == 409
    assert _order(client, order)[0] == "partially_delivered"
