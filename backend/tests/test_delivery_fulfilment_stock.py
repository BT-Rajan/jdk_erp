"""Delivery D5: fulfilling a Delivery Instruction issues each line's
shipment quantity from Finished Goods through the existing single writer,
in the same transaction -- exactly one DELIVERY movement per line,
referencing it; nothing at all when fulfilment fails; never twice."""

from datetime import datetime
from decimal import Decimal

import pytest

from app.api import quotations as quotations_api
from app.api import sales_orders as sales_orders_api
from app.core.errors import ConflictError
from app.core.roles import TEAM_MEMBER
from app.core.security import hash_password
from app.core.timezone import JDK_TIMEZONE
from app.models.customer import Customer
from app.models.delivery_instruction import DeliveryInstruction
from app.models.finished_goods_inventory import DELIVERY, FinishedGoodsInventory, FinishedGoodsMovement
from app.models.product import Product
from app.models.role_permission import RolePermission
from app.models.user import User
from app.services import (
    delivery_instruction_service,
    feasibility_record_service,
    finished_goods_inventory_service,
    quotation_readiness_service,
    working_calendar_service,
)

MONDAY_9AM_KUWAIT = datetime(2026, 9, 28, 9, 0, tzinfo=JDK_TIMEZONE)


def _headers(client, username):
    login = client.post("/api/auth/login", json={"username": username, "password": "Str0ng!Pass"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _stock(db_session, organisation, product, warehouse, quantity):
    finished_goods_inventory_service.receive_finished_goods(
        db_session, organisation_id=organisation.id, product_id=product.id, warehouse_id=warehouse.id,
        quantity=Decimal(quantity), unit_of_measure_id=product.unit_of_measure_id, reference_type="test_seed",
        reference_id=product.id, created_by_user_id=None,
    )
    db_session.commit()


@pytest.fixture()
def setup(client, db_session, organisation, electronics_category, widget_product, warehouse_1, monkeypatch):
    """An order for 100 Widgets and 50 Gadgets. Stock: 60 Widgets, 5 Gadgets."""
    for module in (working_calendar_service, quotations_api, sales_orders_api, feasibility_record_service, quotation_readiness_service):
        monkeypatch.setattr(module, "now_jdk", lambda: MONDAY_9AM_KUWAIT)
    monkeypatch.setattr("app.api.delivery_instructions.now_jdk", lambda: MONDAY_9AM_KUWAIT)
    for username, role in (("salesman_a", TEAM_MEMBER), ("warehouse", "manager")):
        db_session.add(User(
            organisation_id=organisation.id, role=role, full_name=username.title(), email=f"{username}@example.com",
            username=username, password_hash=hash_password("Str0ng!Pass"), is_active=True,
        ))
    db_session.add(RolePermission(organisation_id=organisation.id, role="manager", module_key="inventory", action="deliver", scope="all"))
    db_session.commit()
    gadget = Product(
        organisation_id=organisation.id, code="GDG", name="Gadget", category_id=electronics_category.id,
        unit_of_measure_id=widget_product.unit_of_measure_id, selling_price=50,
        min_selling_price=Decimal("40"), max_selling_price=Decimal("60"), is_active=True,
    )
    widget_product.min_selling_price, widget_product.max_selling_price = Decimal("90"), Decimal("110")
    salesman = db_session.query(User).filter(User.username == "salesman_a").one()
    customer = Customer(
        organisation_id=organisation.id, code="300001", name="A Co", assigned_to_user_id=salesman.id,
        phone="96511111111", address="Shuwaikh", payment_arrangement="after_delivery",
    )
    db_session.add_all([gadget, customer])
    db_session.commit()
    _stock(db_session, organisation, widget_product, warehouse_1, "60")
    _stock(db_session, organisation, gadget, warehouse_1, "5")
    a = _headers(client, "salesman_a")
    lines = [
        {"product_id": widget_product.id, "quantity": "100", "unit_of_measure_id": widget_product.unit_of_measure_id, "unit_price": "100"},
        {"product_id": gadget.id, "quantity": "50", "unit_of_measure_id": gadget.unit_of_measure_id, "unit_price": "50"},
    ]
    quotation = client.post("/api/quotations", json={"customer_id": customer.id, "requested_delivery_date": "2026-10-05", "lines": lines}, headers=a).json()
    client.post(f"/api/quotations/{quotation['id']}/accept", headers=a)
    order = client.post(f"/api/quotations/{quotation['id']}/convert", headers=a).json()
    return order, widget_product, gadget, warehouse_1


def _create(client, order, quantities):
    wh = _headers(client, "warehouse")
    body = {"sales_order_id": order["id"], "lines": [
        {"sales_order_line_id": order["lines"][i]["id"], "quantity": q} for i, q in quantities.items()
    ]}
    instruction = client.post("/api/delivery-instructions", json=body, headers=wh).json()
    for line in instruction["lines"]:  # non-mass products: pallets entered by hand
        client.patch(f"/api/delivery-instructions/{instruction['id']}/lines/{line['id']}", json={"pallet_count": 1}, headers=wh)
    return instruction


def _fulfil(client, instruction):
    return client.post(f"/api/delivery-instructions/{instruction['id']}/fulfil", headers=_headers(client, "warehouse"))


def _on_hand(db_session, product, warehouse):
    db_session.expire_all()
    return db_session.query(FinishedGoodsInventory.quantity_on_hand).filter(
        FinishedGoodsInventory.product_id == product.id, FinishedGoodsInventory.warehouse_id == warehouse.id
    ).scalar()


def _deliveries(db_session):
    return db_session.query(FinishedGoodsMovement).filter(FinishedGoodsMovement.movement_type == DELIVERY).all()


def test_fulfilment_issues_exactly_the_shipment_quantity_once(client, db_session, setup):
    order, widget, _, warehouse = setup
    instruction = _create(client, order, {0: "40"})
    response = _fulfil(client, instruction)
    assert response.status_code == 200 and response.json()["status"] == "fulfilled"

    [movement] = _deliveries(db_session)
    line_id = instruction["lines"][0]["id"]
    assert (movement.reference_type, movement.reference_id) == ("delivery_instruction_line", line_id)
    assert (movement.product_id, movement.quantity, movement.unit_of_measure_id, movement.warehouse_id) == (
        widget.id, Decimal("-40"), widget.unit_of_measure_id, warehouse.id,
    )
    assert _on_hand(db_session, widget, warehouse) == Decimal("20")

    # Double click / API retry: refused, no second movement, stock unchanged.
    for _ in range(3):
        assert _fulfil(client, instruction).status_code == 409
    assert len(_deliveries(db_session)) == 1 and _on_hand(db_session, widget, warehouse) == Decimal("20")
    # The ledger's own duplicate protection also refuses a second issue for the same line.
    with pytest.raises(ConflictError):
        finished_goods_inventory_service.issue_finished_goods(
            db_session, organisation_id=widget.organisation_id, product_id=widget.id, warehouse_id=warehouse.id,
            quantity=Decimal("1"), unit_of_measure_id=widget.unit_of_measure_id,
            reference_type=delivery_instruction_service.FG_REFERENCE_TYPE, reference_id=line_id, created_by_user_id=None,
        )
    db_session.rollback()


def test_insufficient_stock_rejects_the_whole_fulfilment_and_changes_nothing(client, db_session, setup):
    order, widget, gadget, warehouse = setup
    # Widgets are fine (40 of 60) but Gadgets are short (10 of 5): nothing may happen.
    instruction = _create(client, order, {0: "40", 1: "10"})
    response = _fulfil(client, instruction)
    assert response.status_code == 400  # BusinessRuleError, the existing convention
    assert "negative Finished Goods stock" in response.json()["error"]["message"]
    db_session.expire_all()
    assert db_session.get(DeliveryInstruction, instruction["id"]).status == "pending"
    assert _deliveries(db_session) == []
    assert (_on_hand(db_session, widget, warehouse), _on_hand(db_session, gadget, warehouse)) == (Decimal("60"), Decimal("5"))
    # Not clamped or split: after reducing to what is there, it succeeds in full.
    line_id = instruction["lines"][1]["id"]
    client.patch(f"/api/delivery-instructions/{instruction['id']}/lines/{line_id}", json={"quantity": "5"}, headers=_headers(client, "warehouse"))
    assert _fulfil(client, instruction).status_code == 200
    assert len(_deliveries(db_session)) == 2
    assert (_on_hand(db_session, widget, warehouse), _on_hand(db_session, gadget, warehouse)) == (Decimal("20"), Decimal("0"))


def test_not_fulfilled_leaves_stock_alone_and_each_fulfilled_tranche_has_its_own_movement(client, db_session, setup):
    order, widget, _, warehouse = setup
    failed = _create(client, order, {0: "30"})
    client.post(f"/api/delivery-instructions/{failed['id']}/not-fulfilled", json={"reason": "Road closed"}, headers=_headers(client, "warehouse"))
    assert _deliveries(db_session) == [] and _on_hand(db_session, widget, warehouse) == Decimal("60")

    first, second = _create(client, order, {0: "25"}), _create(client, order, {0: "30"})
    assert _fulfil(client, first).status_code == 200 and _fulfil(client, second).status_code == 200
    movements = _deliveries(db_session)
    assert sorted(m.reference_id for m in movements) == sorted([first["lines"][0]["id"], second["lines"][0]["id"]])
    assert _on_hand(db_session, widget, warehouse) == Decimal("5")
