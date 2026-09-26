"""Delivery D2: Delivery Instructions -- manual shipment tranches of a
Sales Order, several per order, numbered YY8NNNN through the shared
numbering helper, each line keeping the Delivery Scrap Allowance % copied
at creation. Needs the inventory:deliver grant. No fulfilment, stock
movement, pallets or Sales Order change yet."""

from datetime import datetime
from decimal import Decimal

import pytest

from app.api import quotations as quotations_api
from app.api import sales_orders as sales_orders_api
from app.core.roles import ADMIN, TEAM_MEMBER
from app.core.security import hash_password
from app.core.timezone import JDK_TIMEZONE
from app.models.audit_event import DELIVERY_INSTRUCTION_CREATED, AuditEvent
from app.models.customer import Customer
from app.models.delivery_instruction import FULFILLED, DeliveryInstruction
from app.models.finished_goods_inventory import FinishedGoodsMovement
from app.models.role_permission import RolePermission
from app.models.sales_order import CANCELLED, COMPLETED, HANDED_OFF, PARTIALLY_DELIVERED, SalesOrder
from app.models.user import User
from app.services import (
    delivery_instruction_service,
    document_numbering,
    feasibility_record_service,
    quotation_readiness_service,
    working_calendar_service,
)

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
def setup(client, db_session, organisation, widget_product, monkeypatch):
    for module in (working_calendar_service, quotations_api, sales_orders_api, feasibility_record_service, quotation_readiness_service):
        monkeypatch.setattr(module, "now_jdk", lambda: MONDAY_9AM_KUWAIT)
    monkeypatch.setattr("app.api.delivery_instructions.now_jdk", lambda: MONDAY_9AM_KUWAIT)
    salesman = _user(db_session, organisation, "salesman_a", TEAM_MEMBER)
    _user(db_session, organisation, "warehouse", TEAM_MEMBER)
    _user(db_session, organisation, "boss", ADMIN)
    # The one new grant, inventory:deliver, for the warehouse user's role
    # (moved to another role in test_unauthorised_users_cannot_create_or_read).
    db_session.add(RolePermission(organisation_id=organisation.id, role=TEAM_MEMBER, module_key="inventory", action="deliver", scope="all"))
    db_session.commit()
    customer = Customer(
        organisation_id=organisation.id, code="300001", name="A Co", assigned_to_user_id=salesman.id,
        phone="96511111111", address="Shuwaikh", payment_arrangement="after_delivery",
    )
    widget_product.min_selling_price, widget_product.max_selling_price = Decimal("90"), Decimal("110")
    db_session.add(customer)
    db_session.commit()
    a = _headers(client, "salesman_a")
    body = {
        "customer_id": customer.id,
        "requested_delivery_date": "2026-10-05",
        "lines": [{"product_id": widget_product.id, "quantity": "100", "unit_of_measure_id": widget_product.unit_of_measure_id, "unit_price": "100"}],
    }
    quotation = client.post("/api/quotations", json=body, headers=a).json()
    client.post(f"/api/quotations/{quotation['id']}/accept", headers=a)
    order = client.post(f"/api/quotations/{quotation['id']}/convert", headers=a).json()
    return order, widget_product


def _create(client, order, quantity, username="warehouse", line_id=None):
    line = line_id or order["lines"][0]["id"]
    return client.post(
        "/api/delivery-instructions",
        json={"sales_order_id": order["id"], "lines": [{"sales_order_line_id": line, "quantity": quantity}]},
        headers=_headers(client, username),
    )


def test_tranches_of_a_handed_off_order_are_numbered_and_audited(client, db_session, setup):
    order, widget = setup
    assert order["status"] == HANDED_OFF
    first = _create(client, order, "40")
    second = _create(client, order, "30")
    third = _create(client, order, "30")
    assert [r.status_code for r in (first, second, third)] == [201, 201, 201]
    numbers = [r.json()["delivery_number"] for r in (first, second, third)]
    # The shared YY?NNNN helper with Delivery Instruction's digit 8.
    assert document_numbering.ESTABLISHED_TYPE_DIGITS["8"] == "Delivery Instruction"
    assert numbers == ["2680001", "2680002", "2680003"]

    instruction = first.json()
    assert (instruction["status"], instruction["sales_order_number"], instruction["customer_name"]) == ("pending", order["order_number"], "A Co")
    line = instruction["lines"][0]
    assert (line["product_id"], line["unit_of_measure_id"]) == (widget.id, widget.unit_of_measure_id)
    assert (Decimal(line["ordered_quantity"]), Decimal(line["quantity"])) == (100, 40)
    listed = client.get(f"/api/delivery-instructions?sales_order_id={order['id']}", headers=_headers(client, "warehouse")).json()
    assert listed["pagination"]["total"] == 3

    events = db_session.query(AuditEvent).filter(AuditEvent.action == DELIVERY_INSTRUCTION_CREATED).all()
    assert len(events) == 3 and f"number: 2680001, sales_order: {order['order_number']}" in events[0].details
    # Records only: the order is unchanged and no stock moved.
    db_session.expire_all()
    assert db_session.get(SalesOrder, order["id"]).status == HANDED_OFF
    assert db_session.query(FinishedGoodsMovement).count() == 0


def test_only_handed_off_or_partially_delivered_orders_are_eligible(client, db_session, setup):
    order, _ = setup
    sales_order = db_session.get(SalesOrder, order["id"])
    for status, expected in ((PARTIALLY_DELIVERED, 201), (CANCELLED, 409), (COMPLETED, 409)):
        sales_order.status = status
        db_session.commit()
        assert _create(client, order, "10").status_code == expected, status


def _position(client, order):
    response = client.get(f"/api/delivery-instructions/position?sales_order_id={order['id']}", headers=_headers(client, "warehouse"))
    assert response.status_code == 200
    body = response.json()
    line = body["lines"][0]
    return body, {k: Decimal(line[k]) for k in (
        "ordered_quantity", "fulfilled_quantity", "remaining_quantity", "ceiling_quantity", "remaining_permitted_quantity"
    )}


def _fulfil(db_session, *instruction_ids):
    # Fulfilment isn't implemented yet: mark instructions fulfilled directly
    # so the cumulative position can be checked.
    for instruction_id in instruction_ids:
        db_session.get(DeliveryInstruction, instruction_id).status = FULFILLED
    db_session.commit()


def test_allowance_is_locked_per_order_and_later_setting_changes_do_not_alter_it(client, db_session, setup):
    order, _ = setup
    admin = _headers(client, "boss")
    client.patch("/api/organisations/me", json={"delivery_scrap_allowance_percent": "2"}, headers=admin)
    body, _ = _position(client, order)
    assert (Decimal(body["scrap_allowance_percent"]), body["allowance_locked"]) == (Decimal("2"), False)

    first = _create(client, order, "40").json()
    client.patch("/api/organisations/me", json={"delivery_scrap_allowance_percent": "10"}, headers=admin)
    second = _create(client, order, "30").json()
    # The first instruction locked 2% for this order; the later setting change alters neither.
    assert [Decimal(i["scrap_allowance_percent"]) for i in (first, second)] == [Decimal("2"), Decimal("2")]
    again = client.get(f"/api/delivery-instructions/{first['id']}", headers=_headers(client, "warehouse")).json()
    assert Decimal(again["scrap_allowance_percent"]) == Decimal("2")
    body, position = _position(client, order)
    assert (Decimal(body["scrap_allowance_percent"]), body["allowance_locked"]) == (Decimal("2"), True)
    # Applied once to the order: 100 t + 2% = 102 t, however many tranches.
    assert position["ceiling_quantity"] == Decimal("102")
    assert "max_permitted_quantity" not in again["lines"][0]


def test_cumulative_ceiling_across_tranches(client, db_session, setup):
    order, _ = setup
    client.patch("/api/organisations/me", json={"delivery_scrap_allowance_percent": "2"}, headers=_headers(client, "boss"))
    di1, di2, di3 = (_create(client, order, q).json() for q in ("40", "40", "22"))
    # Nothing fulfilled yet: pending tranches don't count.
    assert _position(client, order)[1] == {
        "ordered_quantity": Decimal("100"), "fulfilled_quantity": Decimal("0"), "remaining_quantity": Decimal("100"),
        "ceiling_quantity": Decimal("102"), "remaining_permitted_quantity": Decimal("102"),
    }
    _fulfil(db_session, di1["id"], di2["id"])
    _, position = _position(client, order)
    assert (position["fulfilled_quantity"], position["remaining_quantity"], position["remaining_permitted_quantity"]) == (
        Decimal("80"), Decimal("20"), Decimal("22"),
    )
    # 40 + 40 + 22 = 102 is within the one 2% allowance; 40 + 40 + 23 = 103 is detected.
    order_row = db_session.get(SalesOrder, order["id"])
    line_position = delivery_instruction_service.line_position(db_session, order_row.lines[0], Decimal("2"))
    assert not delivery_instruction_service.exceeds_permitted(line_position, Decimal("22"))
    assert delivery_instruction_service.exceeds_permitted(line_position, Decimal("23"))
    _fulfil(db_session, di3["id"])
    _, position = _position(client, order)
    assert (position["fulfilled_quantity"], position["remaining_quantity"], position["remaining_permitted_quantity"]) == (
        Decimal("102"), Decimal("-2"), Decimal("0"),
    )
    # Delivery never changes the Sales Order itself.
    db_session.expire_all()
    order_row = db_session.get(SalesOrder, order["id"])
    assert (order_row.status, order_row.lines[0].quantity) == (HANDED_OFF, Decimal("100"))
    assert db_session.query(FinishedGoodsMovement).count() == 0


def test_a_tranche_may_be_less_than_what_remains(client, db_session, setup):
    order, _ = setup
    di1 = _create(client, order, "40").json()
    _fulfil(db_session, di1["id"])
    assert _position(client, order)[1]["remaining_quantity"] == Decimal("60")
    for quantity in ("20", "30", "50"):
        assert _create(client, order, quantity).status_code == 201


def test_unauthorised_users_cannot_create_or_read(client, db_session, organisation, setup):
    order, _ = setup
    # Move the grant from team members to managers: the salesman now has none.
    grant = db_session.query(RolePermission).filter(RolePermission.action == "deliver").one()
    grant.role = "manager"
    db_session.commit()
    assert _create(client, order, "10", username="salesman_a").status_code == 403
    assert client.get("/api/delivery-instructions", headers=_headers(client, "salesman_a")).status_code == 403
    assert _create(client, order, "10", username="boss").status_code == 201  # Admins always may
    assert db_session.query(AuditEvent).filter(AuditEvent.action == DELIVERY_INSTRUCTION_CREATED).count() == 1


def test_lines_are_validated_server_side(client, setup):
    order, _ = setup
    line_id = order["lines"][0]["id"]
    headers = _headers(client, "warehouse")
    bad = [
        [{"sales_order_line_id": line_id, "quantity": "0"}],
        [{"sales_order_line_id": line_id, "quantity": "1.23456"}],  # more than 4 places -- never rounded
        [{"sales_order_line_id": 999999, "quantity": "1"}],
        [{"sales_order_line_id": line_id, "quantity": "1"}, {"sales_order_line_id": line_id, "quantity": "2"}],
        [],
    ]
    for lines in bad:
        response = client.post("/api/delivery-instructions", json={"sales_order_id": order["id"], "lines": lines}, headers=headers)
        assert response.status_code == 422, lines
