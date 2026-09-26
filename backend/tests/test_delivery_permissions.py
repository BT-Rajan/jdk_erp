"""Delivery D7: every Delivery Instruction route needs `inventory:deliver`
(Admins always have it), and the warehouse's eligible-order list shows
only handed-off and partially delivered orders of the caller's
organisation, across all customers."""

from datetime import datetime
from decimal import Decimal

import pytest

from app.api import quotations as quotations_api
from app.api import sales_orders as sales_orders_api
from app.core.roles import ADMIN, TEAM_MEMBER
from app.core.security import hash_password
from app.core.timezone import JDK_TIMEZONE
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


def _headers(client, username):
    login = client.post("/api/auth/login", json={"username": username, "password": "Str0ng!Pass"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.fixture()
def setup(client, db_session, organisation, widget_product, warehouse_1, monkeypatch):
    """Two handed-off orders (two customers); `warehouse` has the grant,
    `clerk` and the salesman (team members) do not."""
    for module in (working_calendar_service, quotations_api, sales_orders_api, feasibility_record_service, quotation_readiness_service):
        monkeypatch.setattr(module, "now_jdk", lambda: MONDAY_9AM_KUWAIT)
    monkeypatch.setattr("app.api.delivery_instructions.now_jdk", lambda: MONDAY_9AM_KUWAIT)
    for username, role in (("salesman_a", TEAM_MEMBER), ("warehouse", "manager"), ("clerk", TEAM_MEMBER), ("boss", ADMIN)):
        db_session.add(User(
            organisation_id=organisation.id, role=role, full_name=username.title(), email=f"{username}@example.com",
            username=username, password_hash=hash_password("Str0ng!Pass"), is_active=True,
        ))
    db_session.add(RolePermission(organisation_id=organisation.id, role="manager", module_key="inventory", action="deliver", scope="all"))
    db_session.commit()
    salesman = db_session.query(User).filter(User.username == "salesman_a").one()
    customers = [
        Customer(
            organisation_id=organisation.id, code=code, name=name, assigned_to_user_id=salesman.id,
            phone=phone, address="Shuwaikh", payment_arrangement="after_delivery",
        )
        for code, name, phone in (("300001", "Alpha Co", "96511111111"), ("300002", "Beta Co", "96522222222"))
    ]
    widget_product.min_selling_price, widget_product.max_selling_price = Decimal("90"), Decimal("110")
    db_session.add_all(customers)
    db_session.commit()
    finished_goods_inventory_service.receive_finished_goods(
        db_session, organisation_id=organisation.id, product_id=widget_product.id, warehouse_id=warehouse_1.id,
        quantity=Decimal("500"), unit_of_measure_id=widget_product.unit_of_measure_id, reference_type="test_seed",
        reference_id=1, created_by_user_id=None,
    )
    db_session.commit()
    a = _headers(client, "salesman_a")
    line = {"product_id": widget_product.id, "quantity": "10", "unit_of_measure_id": widget_product.unit_of_measure_id, "unit_price": "100"}
    orders = []
    for customer in customers:
        quotation = client.post("/api/quotations", json={"customer_id": customer.id, "requested_delivery_date": "2026-10-05", "lines": [line]}, headers=a).json()
        client.post(f"/api/quotations/{quotation['id']}/accept", headers=a)
        orders.append(client.post(f"/api/quotations/{quotation['id']}/convert", headers=a).json())
    return orders


def _eligible(client, username="warehouse", **params):
    response = client.get("/api/delivery-instructions/eligible-orders", params=params, headers=_headers(client, username))
    assert response.status_code == 200
    return [row["order_number"] for row in response.json()["data"]]


def _create(client, order, quantity, username="warehouse"):
    body = {"sales_order_id": order["id"], "lines": [{"sales_order_line_id": order["lines"][0]["id"], "quantity": quantity}]}
    return client.post("/api/delivery-instructions", json=body, headers=_headers(client, username))


def test_eligible_orders_follow_the_delivery_statuses(client, setup):
    alpha, beta = setup
    assert sorted(_eligible(client)) == sorted([alpha["order_number"], beta["order_number"]])
    assert _eligible(client, q="Beta") == [beta["order_number"]]
    assert _eligible(client, q=alpha["order_number"]) == [alpha["order_number"]]
    # An Admin sees the same list without a grant.
    assert sorted(_eligible(client, "boss")) == sorted([alpha["order_number"], beta["order_number"]])

    wh = _headers(client, "warehouse")
    # Partially delivered stays eligible; completed and cancelled do not.
    first = _create(client, alpha, "4").json()
    client.patch(f"/api/delivery-instructions/{first['id']}/lines/{first['lines'][0]['id']}", json={"pallet_count": 1}, headers=wh)
    assert client.post(f"/api/delivery-instructions/{first['id']}/fulfil", headers=wh).status_code == 200
    assert alpha["order_number"] in _eligible(client)
    client.post(f"/api/sales-orders/{beta['id']}/cancel", json={"reason": "Lost"}, headers=_headers(client, "boss"))
    assert _eligible(client) == [alpha["order_number"]]
    rest = _create(client, alpha, "6").json()
    client.patch(f"/api/delivery-instructions/{rest['id']}/lines/{rest['lines'][0]['id']}", json={"pallet_count": 1}, headers=wh)
    assert client.post(f"/api/delivery-instructions/{rest['id']}/fulfil", headers=wh).status_code == 200
    assert _eligible(client) == []

    position = client.get(f"/api/delivery-instructions/position?sales_order_id={alpha['id']}", headers=wh).json()
    assert (position["sales_order_status"], position["can_create"], position["customer_name"]) == ("completed", False, "Alpha Co")


def test_every_delivery_route_refuses_a_user_without_the_grant(client, setup):
    alpha, _ = setup
    instruction = _create(client, alpha, "4").json()
    line_id = instruction["lines"][0]["id"]
    base = "/api/delivery-instructions"
    calls = [
        ("get", base, None),
        ("get", f"{base}/eligible-orders", None),
        ("get", f"{base}/position?sales_order_id={alpha['id']}", None),
        ("get", f"{base}/{instruction['id']}", None),
        ("post", base, {"sales_order_id": alpha["id"], "lines": [{"sales_order_line_id": alpha["lines"][0]["id"], "quantity": "1"}]}),
        ("patch", f"{base}/{instruction['id']}/lines/{line_id}", {"pallet_count": 2}),
        ("post", f"{base}/{instruction['id']}/fulfil", None),
        ("post", f"{base}/{instruction['id']}/not-fulfilled", {"reason": "No truck"}),
        ("post", f"{base}/{instruction['id']}/retry", None),
    ]
    for username in ("clerk", "salesman_a"):
        headers = _headers(client, username)
        for method, url, body in calls:
            kwargs = {"json": body} if body is not None else {}
            response = getattr(client, method)(url, headers=headers, **kwargs)
            assert response.status_code == 403, (username, method, url)
    # Nothing changed.
    after = client.get(f"{base}/{instruction['id']}", headers=_headers(client, "warehouse")).json()
    assert (after["status"], after["lines"][0]["pallet_count"]) == ("pending", None)
    assert len(client.get(base, headers=_headers(client, "warehouse")).json()["data"]) == 1
