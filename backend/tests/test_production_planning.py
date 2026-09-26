"""P3 -- MRP / Production Planning: what to produce, how much and why.

MRP reads customer demand (Production Requirements -- the current
uncovered demand), FG (on hand / allocated / free), the BOM snapshot and
raw-material stock, and writes only Production Plans (draft -> planned ->
cancelled; customer demand or independent). No inventory, allocation,
Production Order or schedule is ever created here."""

from datetime import datetime
from decimal import Decimal

import pytest

from app.api import quotations as quotations_api
from app.api import sales_orders as sales_orders_api
from app.core.roles import ADMIN, MANAGER, TEAM_MEMBER
from app.core.security import hash_password
from app.core.timezone import JDK_TIMEZONE
from app.models.audit_event import (
    PRODUCTION_PLAN_CANCELLED,
    PRODUCTION_PLAN_CREATED,
    PRODUCTION_PLAN_PLANNED,
    PRODUCTION_PLAN_UPDATED,
    AuditEvent,
)
from app.models.bom import ACTIVE, Bom, BomComponent
from app.models.customer import Customer
from app.models.production_order import ProductionOrder
from app.models.finished_goods_inventory import FinishedGoodsInventory, FinishedGoodsMovement
from app.models.inventory import RawMaterialInventory, StockMovement
from app.models.product import Product
from app.models.production_requirement import ProductionRequirement, SalesOrderLineFulfilment
from app.models.role_permission import RolePermission
from app.models.user import User
from app.models.user_permission import UserPermission
from app.services import (
    feasibility_record_service,
    finished_goods_inventory_service,
    inventory_service,
    quotation_readiness_service,
    working_calendar_service,
)

MONDAY_9AM_KUWAIT = datetime(2026, 9, 28, 9, 0, tzinfo=JDK_TIMEZONE)


def _headers(client, username):
    login = client.post("/api/auth/login", json={"username": username, "password": "Str0ng!Pass"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _fg(db_session, organisation, product, warehouse, quantity, reference_id):
    finished_goods_inventory_service.receive_finished_goods(
        db_session, organisation_id=organisation.id, product_id=product.id, warehouse_id=warehouse.id,
        quantity=Decimal(quantity), unit_of_measure_id=product.unit_of_measure_id, reference_type="test_seed",
        reference_id=reference_id, created_by_user_id=None,
    )
    db_session.commit()


@pytest.fixture()
def setup(client, db_session, organisation, electronics_category, widget_product, cement_raw_material, warehouse_1, monkeypatch):
    """Widget: 600 FG on hand, active BOM (1 Widget <- 2 kg Cement).
    Gadget: no BOM. Cement: 1000 kg on hand. `planner` manages
    Production, `viewer` only views it, `warehouse` allocates FG."""
    for module in (working_calendar_service, quotations_api, sales_orders_api, feasibility_record_service, quotation_readiness_service):
        monkeypatch.setattr(module, "now_jdk", lambda: MONDAY_9AM_KUWAIT)
    users = {}
    for username, role in (
        ("salesman_a", TEAM_MEMBER), ("boss", ADMIN), ("planner", MANAGER), ("viewer", TEAM_MEMBER), ("warehouse", TEAM_MEMBER),
    ):
        users[username] = User(
            organisation_id=organisation.id, role=role, full_name=username.title(), email=f"{username}@example.com",
            username=username, password_hash=hash_password("Str0ng!Pass"), is_active=True,
        )
        db_session.add(users[username])
    db_session.flush()
    for action in ("view", "manage"):
        db_session.add(RolePermission(organisation_id=organisation.id, role=MANAGER, module_key="production", action=action, scope="all"))
    db_session.add(UserPermission(organisation_id=organisation.id, user_id=users["viewer"].id, module_key="production", action="view", scope="all"))
    db_session.add(UserPermission(organisation_id=organisation.id, user_id=users["warehouse"].id, module_key="inventory", action="allocate", scope="all"))
    customer = Customer(
        organisation_id=organisation.id, code="300001", name="A Co", assigned_to_user_id=users["salesman_a"].id,
        phone="96511111111", address="Shuwaikh", payment_arrangement="after_delivery",
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
    _fg(db_session, organisation, widget_product, warehouse_1, "600", 1)
    inventory_service.receive_stock(
        db_session, organisation_id=organisation.id, raw_material_id=cement_raw_material.id, warehouse_id=warehouse_1.id,
        quantity=Decimal("1000"), unit_of_measure_id=cement_raw_material.unit_of_measure_id, reference_type="test_seed",
        reference_id=1, created_by_user_id=None,
    )
    db_session.commit()
    return customer, widget_product, gadget, bom, cement_raw_material, warehouse_1, organisation


def _order(client, customer, product, quantity):
    a = _headers(client, "salesman_a")
    line = {"product_id": product.id, "quantity": quantity, "unit_of_measure_id": product.unit_of_measure_id, "unit_price": "100" if product.name == "Widget" else "50"}
    quotation = client.post("/api/quotations", json={"customer_id": customer.id, "requested_delivery_date": "2026-10-05", "lines": [line]}, headers=a).json()
    client.post(f"/api/quotations/{quotation['id']}/accept", headers=a)
    response = client.post(f"/api/quotations/{quotation['id']}/convert", headers=a)
    assert response.status_code == 201, response.json()
    return response.json()


def _mrp(client, username="planner", **params):
    response = client.get("/api/mrp", params=params, headers=_headers(client, username))
    assert response.status_code == 200, response.json()
    return response.json()


def _requirement_id(db_session):
    return db_session.query(ProductionRequirement.id).order_by(ProductionRequirement.id.desc()).first()[0]


def _plan(client, body, username="planner"):
    return client.post("/api/production-plans", json=body, headers=_headers(client, username))


def _inventory(db_session):
    db_session.expire_all()
    return (
        [r.quantity_on_hand for r in db_session.query(FinishedGoodsInventory).order_by(FinishedGoodsInventory.id)],
        [r.quantity_on_hand for r in db_session.query(RawMaterialInventory).order_by(RawMaterialInventory.id)],
        db_session.query(FinishedGoodsMovement).count(),
        db_session.query(StockMovement).count(),
    )


def _q(row, *keys):
    return [Decimal(row[k]) for k in keys]


def test_customer_demand_appears_with_current_allocation_and_material_needs(client, db_session, setup):
    customer, widget, _, bom, cement, warehouse, organisation = setup
    order = _order(client, customer, widget, "1000")  # 600 allocated at hand-off
    [row] = _mrp(client)["rows"]
    assert (row["demand_type"], row["sales_order_number"], row["line_number"], row["required_by_date"], row["product_name"]) == (
        "customer_demand", order["order_number"], 1, "2026-10-05", "Widget",
    )
    assert _q(row, "required_quantity", "allocated_quantity", "outstanding_quantity", "proposed_quantity") == [1000, 600, 400, 400]
    assert _q(row, "fg_on_hand", "fg_allocated", "fg_free") == [600, 600, 0]
    assert (row["plan_status"], row["bom_status"], row["bom_id"], row["exceptions"]) == ("unplanned", "snapshot", bom.id, [])
    [cement_need] = row["materials"]
    # 2 kg per Widget x 400 to produce, in Cement's own unit.
    assert (cement_need["raw_material_id"], cement_need["unit_of_measure_id"]) == (cement.id, cement.unit_of_measure_id)
    assert _q(cement_need, "required_quantity", "on_hand_quantity", "committed_quantity", "available_quantity", "shortage_quantity") == [
        800, 1000, 0, 1000, 0,
    ]

    # More FG arrives: first free, then allocated -- MRP follows the current
    # allocation, not the one-time hand-off figures.
    _fg(db_session, organisation, widget, warehouse, "300", 2)
    assert _q(_mrp(client)["rows"][0], "fg_on_hand", "fg_free", "outstanding_quantity") == [900, 300, 400]
    body = {"sales_order_line_id": order["lines"][0]["id"], "quantity": "200"}
    assert client.post("/api/fg-allocations/allocate", json=body, headers=_headers(client, "warehouse")).status_code == 200
    row = _mrp(client)["rows"][0]
    assert _q(row, "allocated_quantity", "outstanding_quantity", "fg_free") == [800, 200, 100]
    assert Decimal(row["materials"][0]["required_quantity"]) == 400
    fulfilment = db_session.query(SalesOrderLineFulfilment).one()
    assert (fulfilment.fg_covered_quantity, fulfilment.production_quantity) == (600, 400)  # stale, unused by MRP


def test_missing_bom_and_material_shortage_are_exceptions(client, db_session, setup):
    customer, widget, gadget, _, cement, _, _ = setup
    _order(client, customer, gadget, "25")
    _order(client, customer, widget, "1100")  # 500 outstanding -> 1000 kg Cement
    _order(client, customer, widget, "50")  # 50 outstanding -> 100 kg more
    rows = {(r["product_name"], r["outstanding_quantity"]): r for r in _mrp(client)["rows"]}
    gadget_row = rows[("Gadget", "25.0000")]
    assert (gadget_row["bom_status"], gadget_row["materials"], gadget_row["exceptions"]) == ("bom_required", [], ["bom_required"])
    # Each widget row alone fits the 1000 kg on hand; together they do not.
    assert all(not r["exceptions"] for k, r in rows.items() if k[0] == "Widget")
    [cement_total] = _mrp(client)["material_summary"]
    assert _q(cement_total, "required_quantity", "available_quantity", "shortage_quantity") == [1100, 1000, 100]
    # A single row asking for more than is on hand is flagged itself.
    _order(client, customer, widget, "600")
    short = [r for r in _mrp(client)["rows"] if r["outstanding_quantity"] == "600.0000"][0]
    assert short["exceptions"] == ["material_shortage"] and Decimal(short["materials"][0]["shortage_quantity"]) == 200
    # Filters.
    assert {r["product_name"] for r in _mrp(client, exception="bom_required")["rows"]} == {"Gadget"}
    assert len(_mrp(client, exception="material_shortage")["rows"]) == 1
    assert {r["product_name"] for r in _mrp(client, product_id=gadget.id)["rows"]} == {"Gadget"}
    assert _mrp(client, required_by_from="2026-10-06")["rows"] == []


def test_customer_and_independent_plans_never_touch_inventory_or_orders(client, db_session, setup):
    customer, widget, gadget, bom, cement, _, _ = setup
    order = _order(client, customer, widget, "1000")
    requirement_id = _requirement_id(db_session)
    before = _inventory(db_session)

    created = _plan(client, {"source_type": "customer_demand", "production_requirement_id": requirement_id})
    assert created.status_code == 201, created.json()
    plan = created.json()
    # Defaults to the unplanned demand; traceable; BOM basis copied from the requirement.
    assert (plan["status"], Decimal(plan["planned_quantity"]), Decimal(plan["original_quantity"]), plan["sales_order_number"]) == (
        "draft", 400, 400, order["order_number"],
    )
    assert (plan["bom_id"], [(c["raw_material_id"], Decimal(c["quantity"]), c["unit_of_measure_id"]) for c in plan["components"]]) == (
        bom.id, [(cement.id, 2, cement.unit_of_measure_id)],
    )
    # No accidental duplicate; an additional plan must be explicit -- and may exceed the demand.
    assert _plan(client, {"source_type": "customer_demand", "production_requirement_id": requirement_id}).status_code == 409
    extra = _plan(client, {"source_type": "customer_demand", "production_requirement_id": requirement_id, "planned_quantity": "150", "additional": True})
    assert extra.status_code == 201 and extra.json()["additional"] is True
    row = _mrp(client)["rows"][0]
    assert (row["plan_status"], sorted(row["plan_ids"])) == ("draft", sorted([plan["id"], extra.json()["id"]]))
    assert _q(row, "planned_quantity", "proposed_quantity", "excess_quantity") == [550, 0, 150]
    assert Decimal(row["materials"][0]["required_quantity"]) == 1100  # what is planned, 550 x 2

    # Independent production: explicit product and quantity, no Sales Order.
    independent = _plan(client, {"source_type": "independent", "product_id": widget.id, "planned_quantity": "300", "notes": "Build stock"})
    assert independent.status_code == 201
    body = independent.json()
    assert (body["source_type"], body["production_requirement_id"], body["sales_order_id"], body["bom_id"]) == ("independent", None, None, bom.id)
    ind_row = [r for r in _mrp(client)["rows"] if r["demand_type"] == "independent"][0]
    assert (ind_row["sales_order_number"], ind_row["plan_status"]) == (None, "draft")
    assert _q(ind_row, "planned_quantity", "excess_quantity") == [300, 300]
    # Only in the product's own unit; only a positive quantity.
    assert _plan(client, {"source_type": "independent", "product_id": widget.id, "planned_quantity": "5", "unit_of_measure_id": widget.unit_of_measure_id + 999}).status_code == 422
    assert _plan(client, {"source_type": "independent", "product_id": widget.id, "planned_quantity": "0"}).status_code == 422

    # Accept: planned. A product without a BOM cannot be accepted.
    planned = client.post(f"/api/production-plans/{body['id']}/plan", headers=_headers(client, "planner"))
    assert planned.status_code == 200 and planned.json()["status"] == "planned" and planned.json()["planned_at"]
    no_bom = _plan(client, {"source_type": "independent", "product_id": gadget.id, "planned_quantity": "10"}).json()
    refused = client.post(f"/api/production-plans/{no_bom['id']}/plan", headers=_headers(client, "planner"))
    assert refused.status_code == 409 and "BOM required" in refused.json()["error"]["message"]

    # Nothing moved; no Production Order exists; the order and demand are untouched.
    assert _inventory(db_session) == before
    assert db_session.query(ProductionOrder).count() == 0
    db_session.expire_all()
    assert (Decimal(db_session.get(ProductionRequirement, requirement_id).quantity), db_session.get(ProductionRequirement, requirement_id).status) == (400, "open")
    assert client.get(f"/api/sales-orders/{order['id']}", headers=_headers(client, "boss")).json()["status"] == "handed_off"


def test_cancelled_demand_cannot_become_active_planning(client, db_session, setup):
    customer, widget, _, _, _, _, _ = setup
    order = _order(client, customer, widget, "1000")
    requirement_id = _requirement_id(db_session)
    plan = _plan(client, {"source_type": "customer_demand", "production_requirement_id": requirement_id}).json()
    assert client.post(f"/api/sales-orders/{order['id']}/cancel", json={"reason": "Lost"}, headers=_headers(client, "boss")).status_code == 200

    refused = _plan(client, {"source_type": "customer_demand", "production_requirement_id": requirement_id, "additional": True, "planned_quantity": "5"})
    assert refused.status_code == 409 and "cancelled" in refused.json()["error"]["message"]
    assert client.post(f"/api/production-plans/{plan['id']}/plan", headers=_headers(client, "planner")).status_code == 409
    # The existing draft stays visible, flagged -- it is not silently cancelled.
    [row] = _mrp(client)["rows"]
    assert (row["requirement_status"], row["exceptions"], Decimal(row["outstanding_quantity"])) == ("cancelled", ["demand_cancelled"], 0)


def test_plan_history_is_audited_and_rbac_is_enforced(client, db_session, setup):
    customer, widget, _, _, _, _, _ = setup
    _order(client, customer, widget, "1000")
    plan = _plan(client, {"source_type": "independent", "product_id": widget.id, "planned_quantity": "300"}).json()
    url = f"/api/production-plans/{plan['id']}"

    # Read-only users may view but never change; others see nothing.
    assert client.get("/api/mrp", headers=_headers(client, "viewer")).status_code == 200
    assert client.get(url, headers=_headers(client, "viewer")).status_code == 200
    assert client.patch(url, json={"planned_quantity": "1"}, headers=_headers(client, "viewer")).status_code == 403
    assert _plan(client, {"source_type": "independent", "product_id": widget.id, "planned_quantity": "1"}, username="viewer").status_code == 403
    assert client.post(f"{url}/cancel", json={"reason": "x"}, headers=_headers(client, "viewer")).status_code == 403
    assert client.get("/api/mrp", headers=_headers(client, "salesman_a")).status_code == 403

    edited = client.patch(url, json={"planned_quantity": "350"}, headers=_headers(client, "planner")).json()
    assert (Decimal(edited["planned_quantity"]), Decimal(edited["original_quantity"])) == (350, 300)
    assert client.post(f"{url}/plan", headers=_headers(client, "planner")).status_code == 200
    # Planned plans are not edited; cancelling needs a reason and keeps the record.
    assert client.patch(url, json={"planned_quantity": "400"}, headers=_headers(client, "planner")).status_code == 409
    assert client.post(f"{url}/cancel", json={"reason": " "}, headers=_headers(client, "planner")).status_code == 422
    cancelled = client.post(f"{url}/cancel", json={"reason": "Line down"}, headers=_headers(client, "planner")).json()
    assert (cancelled["status"], cancelled["cancellation_reason"]) == ("cancelled", "Line down") and cancelled["cancelled_at"]
    assert client.post(f"{url}/plan", headers=_headers(client, "planner")).status_code == 409

    def details(action):
        return [e.details for e in db_session.query(AuditEvent).filter(AuditEvent.action == action)]

    assert "planned_quantity 300" in details(PRODUCTION_PLAN_CREATED)[0] and "source: independent" in details(PRODUCTION_PLAN_CREATED)[0]
    assert "planned_quantity: 300 -> 350" in details(PRODUCTION_PLAN_UPDATED)[0]
    assert "draft -> planned" in details(PRODUCTION_PLAN_PLANNED)[0]
    assert "planned -> cancelled; reason: Line down" in details(PRODUCTION_PLAN_CANCELLED)[0]
    assert all(e.actor_user_id for e in db_session.query(AuditEvent).filter(AuditEvent.module == "production", AuditEvent.entity_type == "production_plan"))
