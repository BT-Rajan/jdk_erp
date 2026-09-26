"""Production Requirements follow FG allocation: for each Sales Order line

    uncovered demand = ordered - delivered - allocated

is the requirement's quantity while active; `satisfied` at zero; one
requirement per line, never duplicated; `cancelled` with the order and
never revived. Nothing here moves physical stock or creates production."""

from datetime import datetime
from decimal import Decimal

import pytest

from app.api import quotations as quotations_api
from app.api import sales_orders as sales_orders_api
from app.core.roles import ADMIN, TEAM_MEMBER
from app.core.security import hash_password
from app.core.timezone import JDK_TIMEZONE
from app.models.bom import ACTIVE, Bom, BomComponent
from app.models.customer import Customer
from app.models.production_order import ProductionOrder
from app.models.finished_goods_inventory import FinishedGoodsInventory, FinishedGoodsMovement
from app.models.inventory import StockMovement
from app.models.production_requirement import ProductionRequirement, SalesOrderLineFulfilment
from app.models.role_permission import RolePermission
from app.models.sales_order import SalesOrder
from app.models.user import User
from app.models.user_permission import UserPermission
from app.services import (
    feasibility_record_service,
    finished_goods_inventory_service,
    production_requirement_service,
    quotation_readiness_service,
    working_calendar_service,
)

MONDAY_9AM_KUWAIT = datetime(2026, 9, 28, 9, 0, tzinfo=JDK_TIMEZONE)


def _headers(client, username):
    login = client.post("/api/auth/login", json={"username": username, "password": "Str0ng!Pass"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.fixture()
def setup(client, db_session, organisation, widget_product, cement_raw_material, warehouse_1, monkeypatch):
    """600 Widgets on hand; Widget has an active BOM (1 -> 2 Cement)."""
    for module in (working_calendar_service, quotations_api, sales_orders_api, feasibility_record_service, quotation_readiness_service):
        monkeypatch.setattr(module, "now_jdk", lambda: MONDAY_9AM_KUWAIT)
    users = {}
    for username, role in (("salesman_a", TEAM_MEMBER), ("boss", ADMIN), ("warehouse", TEAM_MEMBER), ("planner", "manager")):
        users[username] = User(
            organisation_id=organisation.id, role=role, full_name=username.title(), email=f"{username}@example.com",
            username=username, password_hash=hash_password("Str0ng!Pass"), is_active=True,
        )
        db_session.add(users[username])
    db_session.flush()
    db_session.add(UserPermission(organisation_id=organisation.id, user_id=users["warehouse"].id, module_key="inventory", action="allocate", scope="all"))
    db_session.add(RolePermission(organisation_id=organisation.id, role="manager", module_key="production", action="view", scope="all"))
    customer = Customer(
        organisation_id=organisation.id, code="300001", name="A Co", assigned_to_user_id=users["salesman_a"].id,
        phone="96511111111", address="Shuwaikh", payment_arrangement="after_delivery",
    )
    widget_product.min_selling_price, widget_product.max_selling_price = Decimal("90"), Decimal("110")
    db_session.add(customer)
    db_session.flush()
    bom = Bom(organisation_id=organisation.id, product_id=widget_product.id, base_quantity=Decimal("1"), status=ACTIVE)
    db_session.add(bom)
    db_session.flush()
    db_session.add(BomComponent(bom_id=bom.id, raw_material_id=cement_raw_material.id, quantity=Decimal("2")))
    db_session.commit()
    _stock(db_session, organisation, widget_product, warehouse_1, "600", 1)
    return customer, widget_product, warehouse_1, bom, organisation


def _stock(db_session, organisation, product, warehouse, quantity, reference_id):
    finished_goods_inventory_service.receive_finished_goods(
        db_session, organisation_id=organisation.id, product_id=product.id, warehouse_id=warehouse.id,
        quantity=Decimal(quantity), unit_of_measure_id=product.unit_of_measure_id, reference_type="test_seed",
        reference_id=reference_id, created_by_user_id=None,
    )
    db_session.commit()


def _order(client, customer, product, quantity):
    a = _headers(client, "salesman_a")
    line = {"product_id": product.id, "quantity": quantity, "unit_of_measure_id": product.unit_of_measure_id, "unit_price": "100"}
    quotation = client.post("/api/quotations", json={"customer_id": customer.id, "requested_delivery_date": "2026-10-05", "lines": [line]}, headers=a).json()
    client.post(f"/api/quotations/{quotation['id']}/accept", headers=a)
    response = client.post(f"/api/quotations/{quotation['id']}/convert", headers=a)
    assert response.status_code == 201, response.json()
    return response.json()


def _requirement(client):
    [row] = client.get("/api/production-requirements", headers=_headers(client, "planner")).json()["data"]
    return row


def _numbers(row):
    return [row["status"]] + [Decimal(row[k]) for k in ("required_quantity", "allocated_quantity", "outstanding_quantity")]


def _allocate(client, order, quantity):
    body = {"sales_order_line_id": order["lines"][0]["id"], "quantity": quantity}
    return client.post("/api/fg-allocations/allocate", json=body, headers=_headers(client, "warehouse"))


def _physical(db_session):
    db_session.expire_all()
    return (
        [r.quantity_on_hand for r in db_session.query(FinishedGoodsInventory)],
        db_session.query(FinishedGoodsMovement).count(),
        db_session.query(StockMovement).count(),
    )


def test_allocation_drives_the_outstanding_demand_to_satisfied(client, db_session, setup):
    customer, widget, warehouse, bom, organisation = setup
    order = _order(client, customer, widget, "1000")
    # 600 allocated at hand-off: 400 outstanding.
    row = _requirement(client)
    assert _numbers(row) == ["open", 1000, 600, 400]
    assert (row["bom_id"], row["required_by_date"], row["sales_order_number"], row["line_number"]) == (
        bom.id, "2026-10-05", order["order_number"], 1,
    )

    # More stock arrives (from anywhere); allocating it reduces the demand.
    _stock(db_session, organisation, widget, warehouse, "400", 2)
    before = _physical(db_session)
    assert _allocate(client, order, "200").status_code == 200
    assert _numbers(_requirement(client)) == ["open", 1000, 800, 200]
    assert _allocate(client, order, "200").status_code == 200
    row = _requirement(client)
    assert _numbers(row) == ["satisfied", 1000, 1000, 0] and row["satisfied_at"]
    # Allocation and requirement updates never touch physical stock.
    assert _physical(db_session) == before

    # Repeated recalculation changes nothing and never duplicates.
    so = db_session.get(SalesOrder, order["id"])
    for _ in range(3):
        assert production_requirement_service.recalculate_line(db_session, so, so.lines[0], Decimal("0")) is None
    db_session.commit()
    assert db_session.query(ProductionRequirement).count() == 1
    # The one-time hand-off figures stay as recorded.
    fulfilment = db_session.query(SalesOrderLineFulfilment).one()
    assert (fulfilment.fg_covered_quantity, fulfilment.production_quantity) == (600, 400)
    # The BOM snapshot is untouched by later BOM edits.
    db_session.query(BomComponent).update({BomComponent.quantity: Decimal("9")})
    db_session.commit()
    assert [Decimal(c["quantity"]) for c in _requirement(client)["components"]] == [2]


def test_cancelled_demand_stays_cancelled_even_when_allocation_is_released(client, db_session, setup):
    customer, widget, _, _, _ = setup
    order = _order(client, customer, widget, "1000")
    before = _physical(db_session)
    assert client.post(f"/api/sales-orders/{order['id']}/cancel", json={"reason": "Lost"}, headers=_headers(client, "boss")).status_code == 200
    row = _requirement(client)
    assert (row["status"], Decimal(row["outstanding_quantity"]), Decimal(row["allocated_quantity"])) == ("cancelled", 0, 0)
    # A later release (nothing left) or recalculation never revives it.
    body = {"sales_order_line_id": order["lines"][0]["id"], "reason": "tidy up"}
    assert client.post("/api/fg-allocations/release", json=body, headers=_headers(client, "boss")).status_code == 200
    so = db_session.get(SalesOrder, order["id"])
    assert production_requirement_service.recalculate_line(db_session, so, so.lines[0], Decimal("0")) is None
    assert _requirement(client)["status"] == "cancelled"
    assert db_session.query(ProductionRequirement).count() == 1
    assert _physical(db_session) == before


def test_a_missing_bom_is_flagged_and_the_required_by_date_follows_the_order(client, db_session, setup):
    customer, widget, _, bom, _ = setup
    db_session.delete(db_session.query(BomComponent).one())
    db_session.delete(bom)
    db_session.commit()
    order = _order(client, customer, widget, "700")
    row = _requirement(client)
    assert (row["status"], Decimal(row["outstanding_quantity"]), row["bom_id"]) == ("bom_required", 100, None)
    moved = {"reason": "Customer asked", "requested_delivery_date": "2026-10-12"}
    assert client.patch(f"/api/sales-orders/{order['id']}", json=moved, headers=_headers(client, "boss")).status_code == 200
    assert _requirement(client)["required_by_date"] == "2026-10-12"


def test_requirement_and_allocation_changes_create_no_production_order(client, db_session, setup):
    customer, widget, _, _, _ = setup
    order = _order(client, customer, widget, "1000")
    assert _allocate(client, order, "1").status_code == 409  # nothing free; demand stays
    assert db_session.query(ProductionOrder).count() == 0
