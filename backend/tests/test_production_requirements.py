"""Sales S15.2: at hand-off each Sales Order line is covered from Finished
Goods first; only the shortfall becomes a Production Requirement (with a
snapshot of the product's active BOM, or flagged bom_required). Records
only -- the Sales Order stays the commercial source of truth."""

from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.api import quotations as quotations_api
from app.api import sales_orders as sales_orders_api
from app.core.errors import ConflictError
from app.core.roles import ADMIN, TEAM_MEMBER
from app.core.security import hash_password
from app.core.timezone import JDK_TIMEZONE
from app.models.audit_event import FULFILMENT_ASSESSED, AuditEvent
from app.models.bom import ACTIVE, Bom, BomComponent
from app.models.customer import Customer
from app.models.product import Product
from app.models.production_requirement import ProductionRequirement, SalesOrderLineFulfilment
from app.models.sales_order import SalesOrder
from app.models.user import User
from app.services import (
    feasibility_record_service,
    finished_goods_inventory_service,
    production_requirement_service,
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


def _stock(db_session, organisation, product, warehouse, quantity):
    finished_goods_inventory_service.receive_finished_goods(
        db_session, organisation_id=organisation.id, product_id=product.id, warehouse_id=warehouse.id,
        quantity=Decimal(quantity), unit_of_measure_id=product.unit_of_measure_id, reference_type="test_seed",
        reference_id=product.id, created_by_user_id=None,
    )
    db_session.commit()


@pytest.fixture()
def setup(db_session, organisation, electronics_category, widget_product, cement_raw_material, warehouse_1, monkeypatch):
    """Widget: 40 on hand, active BOM (1 -> 2 kg Cement). Gadget: 10 on
    hand, no BOM. Customer complete for hand-off."""
    for module in (working_calendar_service, quotations_api, sales_orders_api, feasibility_record_service, quotation_readiness_service):
        monkeypatch.setattr(module, "now_jdk", lambda: MONDAY_9AM_KUWAIT)
    salesman = _user(db_session, organisation, "salesman_a", TEAM_MEMBER)
    _user(db_session, organisation, "boss", ADMIN)
    customer = Customer(
        organisation_id=organisation.id, code="300001", name="A Co", assigned_to_user_id=salesman.id,
        phone="96511111111", address="Shuwaikh", payment_arrangement="before_delivery",
    )
    gadget = Product(
        organisation_id=organisation.id, code="PRD002", name="Gadget", category_id=electronics_category.id,
        unit_of_measure_id=widget_product.unit_of_measure_id, selling_price=50, is_active=True,
        min_selling_price=Decimal("40"), max_selling_price=Decimal("60"),
    )
    widget_product.min_selling_price, widget_product.max_selling_price = Decimal("90"), Decimal("110")
    db_session.add_all([customer, gadget])
    db_session.flush()
    bom = Bom(organisation_id=organisation.id, product_id=widget_product.id, base_quantity=Decimal("1"), status=ACTIVE)
    db_session.add(bom)
    db_session.flush()
    db_session.add(BomComponent(bom_id=bom.id, raw_material_id=cement_raw_material.id, quantity=Decimal("2")))
    db_session.commit()
    _stock(db_session, organisation, widget_product, warehouse_1, "40")
    _stock(db_session, organisation, gadget, warehouse_1, "10")
    return customer, widget_product, gadget, bom, cement_raw_material


def _line(product, quantity, price):
    return {"product_id": product.id, "quantity": quantity, "unit_of_measure_id": product.unit_of_measure_id, "unit_price": price}


def _order(client, customer, lines, convert=True):
    a = _headers(client, "salesman_a")
    body = {"customer_id": customer.id, "requested_delivery_date": "2026-10-05", "lines": lines}
    quotation = client.post("/api/quotations", json=body, headers=a).json()
    assert client.post(f"/api/quotations/{quotation['id']}/accept", headers=a).status_code == 200
    if not convert:
        return quotation
    response = client.post(f"/api/quotations/{quotation['id']}/convert", headers=a)
    assert response.status_code == 201, response.json()
    return response.json()


def _fulfilment(client, order_id):
    return client.get(f"/api/sales-orders/{order_id}/fulfilment", headers=_headers(client, "salesman_a")).json()


def test_each_line_uses_stock_first_and_only_the_shortfall_needs_production(client, db_session, setup):
    customer, widget, gadget, bom, cement = setup
    order = _order(client, customer, [_line(widget, "100", "100"), _line(gadget, "5", "50")])

    widget_line, gadget_line = _fulfilment(client, order["id"])
    # Widget: 40 from stock, 60 to produce -- one requirement for that line only.
    assert (widget_line["line_number"], widget_line["result"]) == (1, "production_required")
    assert [Decimal(widget_line[k]) for k in ("fg_available_quantity", "fg_covered_quantity", "production_quantity")] == [40, 40, 60]
    requirement = widget_line["production_requirement"]
    assert (requirement["sales_order_line_id"], requirement["product_id"], requirement["unit_of_measure_id"]) == (
        order["lines"][0]["id"], widget.id, widget.unit_of_measure_id,
    )
    assert (Decimal(requirement["quantity"]), requirement["status"], requirement["required_by_date"]) == (60, "open", "2026-10-05")
    assert (requirement["bom_id"], Decimal(requirement["bom_base_quantity"])) == (bom.id, 1)
    assert [(c["raw_material_id"], Decimal(c["quantity"]), c["unit_of_measure_id"]) for c in requirement["components"]] == [
        (cement.id, Decimal("2"), cement.unit_of_measure_id)
    ]
    # Gadget: fully covered -- a result, but no production record.
    assert (gadget_line["result"], Decimal(gadget_line["fg_covered_quantity"]), gadget_line["production_requirement"]) == ("from_stock", 5, None)
    assert db_session.query(ProductionRequirement).count() == 1
    assert "to produce 60" in db_session.query(AuditEvent).filter(AuditEvent.action == FULFILMENT_ASSESSED).one().details

    # A later BOM edit never changes the snapshot.
    db_session.query(BomComponent).filter(BomComponent.bom_id == bom.id).update({"quantity": Decimal("3")})
    db_session.commit()
    assert Decimal(_fulfilment(client, order["id"])[0]["production_requirement"]["components"][0]["quantity"]) == 2


def test_lines_of_one_product_share_stock_and_a_missing_bom_is_flagged(client, db_session, setup):
    customer, widget, gadget, bom, cement = setup
    order = _order(client, customer, [_line(widget, "30", "100"), _line(widget, "30", "100"), _line(gadget, "25", "50")])
    first, second, third = _fulfilment(client, order["id"])
    assert (first["result"], first["production_requirement"]) == ("from_stock", None)
    assert [Decimal(second[k]) for k in ("fg_available_quantity", "fg_covered_quantity", "production_quantity")] == [10, 10, 20]
    assert Decimal(second["production_requirement"]["quantity"]) == 20
    # Gadget has no active BOM: the demand is still recorded, flagged.
    flagged = third["production_requirement"]
    assert (Decimal(flagged["quantity"]), flagged["status"], flagged["bom_id"], flagged["components"]) == (15, "bom_required", None, [])


def test_only_a_handed_off_order_once_and_never_an_invalid_quantity(client, db_session, setup):
    customer, widget, gadget, bom, cement = setup
    order = db_session.get(SalesOrder, _order(client, customer, [_line(widget, "100", "100")])["id"])
    with pytest.raises(ConflictError):  # already assessed at hand-off
        production_requirement_service.create_for_order(db_session, order)

    duplicate = ProductionRequirement(
        organisation_id=order.organisation_id, sales_order_id=order.id, sales_order_line_id=order.lines[0].id,
        product_id=widget.id, quantity=Decimal("1"), unit_of_measure_id=widget.unit_of_measure_id, status="open",
    )
    db_session.add(duplicate)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    client.post(f"/api/sales-orders/{order.id}/cancel", json={"reason": "Lost"}, headers=_headers(client, "boss"))
    db_session.expire_all()
    db_session.query(SalesOrderLineFulfilment).delete()
    db_session.query(ProductionRequirement).delete()
    db_session.commit()
    with pytest.raises(ConflictError):  # cancelled, so not handed off
        production_requirement_service.create_for_order(db_session, db_session.get(SalesOrder, order.id))

    zero = ProductionRequirement(
        organisation_id=order.organisation_id, sales_order_id=order.id, sales_order_line_id=order.lines[0].id,
        product_id=widget.id, quantity=Decimal("0"), unit_of_measure_id=widget.unit_of_measure_id, status="open",
    )
    db_session.add(zero)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_a_line_not_in_the_products_unit_is_refused(client, db_session, setup, mass_tonne_unit):
    customer, widget, gadget, bom, cement = setup
    quotation = _order(client, customer, [_line(widget, "100", "100")], convert=False)
    widget.unit_of_measure_id = mass_tonne_unit.id  # the product's unit changed after quoting
    db_session.commit()

    response = client.post(f"/api/quotations/{quotation['id']}/convert", headers=_headers(client, "salesman_a"))
    assert response.status_code == 422 and "nothing is converted" in response.json()["error"]["message"]
    assert db_session.query(SalesOrder).count() == 0
    assert db_session.query(SalesOrderLineFulfilment).count() == 0


def test_production_side_cannot_change_sales_data(client, db_session, setup):
    customer, widget, gadget, bom, cement = setup
    order = _order(client, customer, [_line(widget, "100", "100")])
    url, admin = f"/api/sales-orders/{order['id']}", _headers(client, "boss")

    for method in (client.post, client.put, client.patch):
        assert method(f"{url}/fulfilment", json={"quantity": "1"}, headers=admin).status_code == 405
    # Changing the assessed quantity must be resolved first; date and price may change.
    assert client.patch(url, json={"reason": "More", "lines": [_line(widget, "120", "100")]}, headers=admin).status_code == 409
    moved = client.patch(url, json={"reason": "Later", "requested_delivery_date": "2026-10-07", "lines": [_line(widget, "100", "95")]}, headers=admin)
    assert moved.status_code == 200

    requirement = _fulfilment(client, order["id"])[0]["production_requirement"]
    assert (Decimal(requirement["quantity"]), requirement["required_by_date"]) == (60, "2026-10-07")  # date read from the order
    current = client.get(url, headers=admin).json()
    assert (current["customer_id"], Decimal(current["lines"][0]["quantity"])) == (customer.id, 100)
