"""Delivery D3: a pending Delivery Instruction's shipment quantity and
pallets. Quantity in the line's stock unit, within the order line's
remaining permitted quantity (cumulative allowance) unless an Admin
overrides with a reason. Pallets: default max(1, ceil(tonnes)) for mass
products via the organisation's TON unit, manual otherwise; whole number
>= 1; a manual count survives quantity changes. No stock or Sales Order
change."""

from datetime import datetime
from decimal import Decimal

import pytest

from app.api import quotations as quotations_api
from app.api import sales_orders as sales_orders_api
from app.core.roles import ADMIN, TEAM_MEMBER
from app.core.security import hash_password
from app.core.timezone import JDK_TIMEZONE
from app.models.audit_event import DELIVERY_SHIPMENT_UPDATED, AuditEvent
from app.models.customer import Customer
from app.models.finished_goods_inventory import FinishedGoodsMovement
from app.models.product import Product
from app.models.role_permission import RolePermission
from app.models.sales_order import HANDED_OFF, SalesOrder
from app.models.unit import UnitOfMeasure
from app.models.user import User
from app.services import feasibility_record_service, quotation_readiness_service, working_calendar_service

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
def setup(client, db_session, organisation, electronics_category, widget_product, monkeypatch):
    """One order: 20 000 kg of Blocks (mass; the organisation has a TON
    unit) and 100 Widgets (a unit with no mass dimension)."""
    for module in (working_calendar_service, quotations_api, sales_orders_api, feasibility_record_service, quotation_readiness_service):
        monkeypatch.setattr(module, "now_jdk", lambda: MONDAY_9AM_KUWAIT)
    monkeypatch.setattr("app.api.delivery_instructions.now_jdk", lambda: MONDAY_9AM_KUWAIT)
    for username, role in (("salesman_a", TEAM_MEMBER), ("warehouse", "manager"), ("boss", ADMIN)):
        _user(db_session, organisation, username, role)
    db_session.add(RolePermission(organisation_id=organisation.id, role="manager", module_key="inventory", action="deliver", scope="all"))
    kg = UnitOfMeasure(organisation_id=organisation.id, name="Mass Kilogram", code="KGM", dimension="mass", conversion_factor_to_base=1, is_active=True)
    ton = UnitOfMeasure(organisation_id=organisation.id, name="Tonne", code="TON", dimension="mass", conversion_factor_to_base=1000, is_active=True)
    db_session.add_all([kg, ton])
    db_session.flush()
    blocks = Product(
        organisation_id=organisation.id, code="BLK", name="Blocks", category_id=electronics_category.id, unit_of_measure_id=kg.id,
        selling_price=1, min_selling_price=Decimal("1"), max_selling_price=Decimal("2"), is_active=True,
    )
    widget_product.min_selling_price, widget_product.max_selling_price = Decimal("90"), Decimal("110")
    salesman = db_session.query(User).filter(User.username == "salesman_a").one()
    customer = Customer(
        organisation_id=organisation.id, code="300001", name="A Co", assigned_to_user_id=salesman.id,
        phone="96511111111", address="Shuwaikh", payment_arrangement="after_delivery",
    )
    db_session.add_all([blocks, customer])
    db_session.commit()
    a = _headers(client, "salesman_a")
    lines = [
        {"product_id": blocks.id, "quantity": "20000", "unit_of_measure_id": kg.id, "unit_price": "1"},
        {"product_id": widget_product.id, "quantity": "100", "unit_of_measure_id": widget_product.unit_of_measure_id, "unit_price": "100"},
    ]
    quotation = client.post("/api/quotations", json={"customer_id": customer.id, "requested_delivery_date": "2026-10-05", "lines": lines}, headers=a).json()
    client.post(f"/api/quotations/{quotation['id']}/accept", headers=a)
    order = client.post(f"/api/quotations/{quotation['id']}/convert", headers=a).json()
    blocks_line, widget_line = order["lines"]
    wh = _headers(client, "warehouse")
    instruction = client.post(
        "/api/delivery-instructions",
        json={"sales_order_id": order["id"], "lines": [
            {"sales_order_line_id": blocks_line["id"], "quantity": "10000"},
            {"sales_order_line_id": widget_line["id"], "quantity": "10"},
        ]},
        headers=wh,
    ).json()
    return order, instruction, kg


def _patch(client, instruction, index, body, username="warehouse"):
    line_id = instruction["lines"][index]["id"]
    return client.patch(f"/api/delivery-instructions/{instruction['id']}/lines/{line_id}", json=body, headers=_headers(client, username))


def _line(response, index=0):
    return response.json()["lines"][index]


def test_quantity_is_positive_in_the_stock_unit_and_within_the_remaining_permitted(client, db_session, setup):
    order, instruction, kg = setup
    ok = _patch(client, instruction, 0, {"quantity": "12000", "unit_of_measure_id": kg.id})
    assert ok.status_code == 200 and Decimal(_line(ok)["quantity"]) == Decimal("12000")
    for bad in ({"quantity": "0"}, {"quantity": "-5"}, {"quantity": "5", "unit_of_measure_id": kg.id + 999}):
        assert _patch(client, instruction, 0, bad).status_code == 422, bad
    # 20 000 kg ordered, 0% allowance, nothing fulfilled: 20 001 is too much for the warehouse...
    assert _patch(client, instruction, 0, {"quantity": "20001"}).status_code == 422
    # ...and for an Admin without a reason; an Admin with a reason may.
    assert _patch(client, instruction, 0, {"quantity": "20001"}, "boss").status_code == 422
    override = _patch(client, instruction, 0, {"quantity": "20001", "override_reason": "Customer accepted the extra"}, "boss")
    assert override.status_code == 200 and _line(override)["quantity_override_reason"] == "Customer accepted the extra"
    # Back within the limit, the override reason no longer applies.
    assert _line(_patch(client, instruction, 0, {"quantity": "15000"}))["quantity_override_reason"] is None


@pytest.mark.parametrize("kg_quantity, pallets", [("10000", 10), ("10200", 11), ("500", 1), ("100", 1)])
def test_mass_pallet_default_is_ceiling_tonnes_with_a_minimum_of_one(client, setup, kg_quantity, pallets):
    order, instruction, kg = setup
    line = _line(_patch(client, instruction, 0, {"quantity": kg_quantity}))
    assert (line["pallet_count_default"], line["pallet_count"], line["pallet_count_manual"]) == (pallets, pallets, False)


def test_non_mass_products_need_a_manual_pallet_count(client, setup):
    order, instruction, _ = setup
    widget = instruction["lines"][1]
    assert (widget["pallet_count_default"], widget["pallet_count"]) == (None, None)
    assert _patch(client, instruction, 1, {"quantity": "12"}).status_code == 422
    line = _line(_patch(client, instruction, 1, {"quantity": "12", "pallet_count": 2}), 1)
    assert (line["pallet_count_default"], line["pallet_count"], line["pallet_count_manual"]) == (None, 2, True)


def test_warehouse_may_raise_or_lower_pallets_but_never_to_zero(client, setup):
    order, instruction, _ = setup
    assert instruction["lines"][0]["pallet_count"] == 10  # 10 000 kg
    assert _line(_patch(client, instruction, 0, {"pallet_count": 12}))["pallet_count"] == 12
    assert _line(_patch(client, instruction, 0, {"pallet_count": 8}))["pallet_count"] == 8
    for bad in (0, -1, 1.5, "3"):
        assert _patch(client, instruction, 0, {"pallet_count": bad}).status_code == 422, bad


def test_changing_the_quantity_recalculates_the_default_without_overwriting_a_manual_count(client, db_session, setup):
    order, instruction, _ = setup
    line = _line(_patch(client, instruction, 0, {"quantity": "10200"}))
    assert (line["pallet_count_default"], line["pallet_count"]) == (11, 11)  # automatic: follows the default
    _patch(client, instruction, 0, {"pallet_count": 9})
    line = _line(_patch(client, instruction, 0, {"quantity": "14500"}))
    assert (line["pallet_count_default"], line["pallet_count"], line["pallet_count_manual"]) == (15, 9, True)
    line = _line(_patch(client, instruction, 0, {"pallet_count": None}))  # back to the default
    assert (line["pallet_count"], line["pallet_count_manual"]) == (15, False)

    events = db_session.query(AuditEvent).filter(AuditEvent.action == DELIVERY_SHIPMENT_UPDATED).all()
    assert any("quantity: 10000.0000 -> 10200" in e.details for e in events)
    assert any("pallet_count: 11 -> 9" in e.details for e in events)
    # No stock moved; the Sales Order is untouched.
    assert db_session.query(FinishedGoodsMovement).count() == 0
    db_session.expire_all()
    sales_order = db_session.get(SalesOrder, order["id"])
    assert (sales_order.status, [line.quantity for line in sales_order.lines]) == (HANDED_OFF, [Decimal("20000"), Decimal("100")])
