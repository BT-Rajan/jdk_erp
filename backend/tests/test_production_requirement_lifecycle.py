"""A Production Requirement is a demand/reference record -- the part of a
Sales Order line not covered by delivered or allocated FG -- never a
production command. bom_required -> open (BOM snapshot, once); active <->
satisfied as the uncovered demand (ordered - delivered - allocated)
reaches zero or reappears; -> cancelled with the order, final. Never
deleted; audited; nothing moves in inventory."""

from datetime import datetime
from decimal import Decimal

import pytest

from app.api import quotations as quotations_api
from app.api import sales_orders as sales_orders_api
from app.core.roles import ADMIN, MANAGER, TEAM_MEMBER
from app.core.security import hash_password
from app.core.timezone import JDK_TIMEZONE
from app.models.audit_event import (
    PRODUCTION_REQUIREMENT_BOM_RESOLVED,
    PRODUCTION_REQUIREMENT_CANCELLED,
    PRODUCTION_REQUIREMENT_CREATED,
    PRODUCTION_REQUIREMENT_SATISFIED,
    PRODUCTION_REQUIREMENT_QUANTITY_CHANGED,
    PRODUCTION_REQUIREMENT_REOPENED,
    AuditEvent,
)
from app.models.bom import ACTIVE, Bom, BomComponent
from app.models.customer import Customer
from app.models.finished_goods_inventory import FinishedGoodsMovement
from app.models.inventory import StockMovement
from app.models.product import Product
from app.models.production_requirement import ProductionRequirement, SalesOrderLineFulfilment
from app.models.role_permission import RolePermission
from app.models.user import User
from app.models.user_permission import UserPermission
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


def _stock(db_session, organisation, product, warehouse, quantity, reference_id):
    finished_goods_inventory_service.receive_finished_goods(
        db_session, organisation_id=organisation.id, product_id=product.id, warehouse_id=warehouse.id,
        quantity=Decimal(quantity), unit_of_measure_id=product.unit_of_measure_id, reference_type="test_seed",
        reference_id=reference_id, created_by_user_id=None,
    )
    db_session.commit()


@pytest.fixture()
def setup(client, db_session, organisation, electronics_category, widget_product, cement_raw_material, warehouse_1, monkeypatch):
    """Widget: 40 on hand, active BOM (1 -> 2 of Cement). Gadget: 10 on
    hand, no BOM. `planner` views Production, `lead` also manages it,
    `warehouse` delivers."""
    for module in (working_calendar_service, quotations_api, sales_orders_api, feasibility_record_service, quotation_readiness_service):
        monkeypatch.setattr(module, "now_jdk", lambda: MONDAY_9AM_KUWAIT)
    monkeypatch.setattr("app.api.delivery_instructions.now_jdk", lambda: MONDAY_9AM_KUWAIT)
    users = {}
    for username, role in (
        ("salesman_a", TEAM_MEMBER), ("boss", ADMIN), ("planner", MANAGER), ("lead", MANAGER), ("warehouse", TEAM_MEMBER),
    ):
        users[username] = User(
            organisation_id=organisation.id, role=role, full_name=username.title(), email=f"{username}@example.com",
            username=username, password_hash=hash_password("Str0ng!Pass"), is_active=True,
        )
        db_session.add(users[username])
    db_session.flush()
    # Managers view Production; only `lead` also manages it; `warehouse` delivers.
    db_session.add(RolePermission(organisation_id=organisation.id, role=MANAGER, module_key="production", action="view", scope="all"))
    for username, module_key, action in (("lead", "production", "manage"), ("warehouse", "inventory", "deliver")):
        db_session.add(UserPermission(
            organisation_id=organisation.id, user_id=users[username].id, module_key=module_key, action=action, scope="all",
        ))
    db_session.commit()
    salesman = db_session.query(User).filter(User.username == "salesman_a").one()
    customer = Customer(
        organisation_id=organisation.id, code="300001", name="A Co", assigned_to_user_id=salesman.id,
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
    _stock(db_session, organisation, widget_product, warehouse_1, "40", 1)
    _stock(db_session, organisation, gadget, warehouse_1, "10", 2)
    return customer, widget_product, gadget, bom, cement_raw_material, warehouse_1


def _order(client, customer, lines):
    a = _headers(client, "salesman_a")
    body = {"customer_id": customer.id, "requested_delivery_date": "2026-10-05", "lines": [
        {"product_id": p.id, "quantity": q, "unit_of_measure_id": p.unit_of_measure_id, "unit_price": price} for p, q, price in lines
    ]}
    quotation = client.post("/api/quotations", json=body, headers=a).json()
    client.post(f"/api/quotations/{quotation['id']}/accept", headers=a)
    response = client.post(f"/api/quotations/{quotation['id']}/convert", headers=a)
    assert response.status_code == 201, response.json()
    return response.json()


def _requirements(client, username="planner", **params):
    response = client.get("/api/production-requirements", params=params, headers=_headers(client, username))
    assert response.status_code == 200, response.json()
    return response.json()["data"]


def _requirement(client, requirement_id):
    return client.get(f"/api/production-requirements/{requirement_id}", headers=_headers(client, "planner")).json()


def _audits(db_session, action):
    return [e.details for e in db_session.query(AuditEvent).filter(AuditEvent.action == action).order_by(AuditEvent.id)]


def _inventory_counts(db_session):
    return db_session.query(FinishedGoodsMovement).count(), db_session.query(StockMovement).count()


def _edit(client, order, quantity, price="100", confirm=None):
    line = order["lines"][0]
    body = {"reason": "Customer changed", "lines": [
        {"product_id": line["product_id"], "quantity": quantity, "unit_of_measure_id": line["unit_of_measure_id"], "unit_price": price}
    ]}
    if confirm is not None:
        body["confirm_fulfilment_change"] = confirm
    return client.patch(f"/api/sales-orders/{order['id']}", json=body, headers=_headers(client, "boss"))


def test_hand_off_requirement_is_visible_to_production_with_its_demand_position(client, db_session, setup):
    customer, widget, _, bom, cement, _ = setup
    order = _order(client, customer, [(widget, "100", "100")])
    [row] = _requirements(client)
    assert (row["sales_order_number"], row["line_number"], row["product_name"], row["customer_name"]) == (
        order["order_number"], 1, widget.name, "A Co",
    )
    assert [
        Decimal(row[k])
        for k in ("ordered_quantity", "covered_quantity", "quantity", "delivered_quantity", "required_quantity", "allocated_quantity", "outstanding_quantity")
    ] == [100, 40, 60, 0, 100, 40, 60]
    assert (row["status"], row["required_by_date"], row["bom_id"], row["can_resolve_bom"]) == ("open", "2026-10-05", bom.id, False)
    assert [(c["raw_material_id"], Decimal(c["quantity"])) for c in row["components"]] == [(cement.id, 2)]
    assert _requirements(client, status="cancelled") == [] and len(_requirements(client, q=order["order_number"])) == 1

    # Production permission, enforced server-side: no grant -> 403; view is not manage.
    assert client.get("/api/production-requirements", headers=_headers(client, "salesman_a")).status_code == 403
    assert client.get(f"/api/production-requirements/{row['id']}", headers=_headers(client, "warehouse")).status_code == 403
    assert client.post(f"/api/production-requirements/{row['id']}/snapshot-bom", headers=_headers(client, "planner")).status_code == 403


def test_bom_required_becomes_open_with_a_permanent_snapshot(client, db_session, setup):
    customer, widget, gadget, bom, cement, _ = setup
    order = _order(client, customer, [(gadget, "25", "50")])
    [row] = _requirements(client, "lead")
    assert (row["status"], Decimal(row["quantity"]), row["bom_id"], row["components"], row["can_resolve_bom"]) == (
        "bom_required", 15, None, [], True,
    )
    url = f"/api/production-requirements/{row['id']}/snapshot-bom"
    lead = _headers(client, "lead")
    before = _inventory_counts(db_session)
    # No active BOM yet: refused, nothing changes.
    refused = client.post(url, headers=lead)
    assert refused.status_code == 409 and "no active BOM" in refused.json()["error"]["message"]
    draft = Bom(organisation_id=widget.organisation_id, product_id=gadget.id, base_quantity=Decimal("5"), status="draft")
    db_session.add(draft)
    db_session.flush()
    db_session.add(BomComponent(bom_id=draft.id, raw_material_id=cement.id, quantity=Decimal("3")))
    db_session.commit()
    assert client.post(url, headers=lead).status_code == 409  # a draft BOM does not count
    draft.status = ACTIVE
    db_session.commit()

    resolved = client.post(url, headers=lead).json()
    assert (resolved["status"], Decimal(resolved["quantity"]), resolved["bom_id"], Decimal(resolved["bom_base_quantity"])) == (
        "open", 15, draft.id, 5,
    )
    assert [(c["raw_material_id"], Decimal(c["quantity"]), c["unit_of_measure_id"]) for c in resolved["components"]] == [
        (cement.id, 3, cement.unit_of_measure_id),
    ]
    assert client.post(url, headers=lead).status_code == 409  # once only
    assert len(_audits(db_session, PRODUCTION_REQUIREMENT_BOM_RESOLVED)) == 1
    assert _inventory_counts(db_session) == before

    # Later BOM edits never reach either snapshot (resolved, or taken at hand-off).
    widget_order = _order(client, customer, [(widget, "100", "100")])
    db_session.query(BomComponent).update({BomComponent.quantity: Decimal("9")})
    db_session.query(Bom).update({Bom.base_quantity: Decimal("7")})
    db_session.commit()
    for requirement in _requirements(client):
        assert (Decimal(requirement["bom_base_quantity"]), Decimal(requirement["components"][0]["quantity"])) in ((5, 3), (1, 2))
    assert {r["sales_order_number"] for r in _requirements(client)} == {order["order_number"], widget_order["order_number"]}


def test_cancelling_the_order_cancels_its_requirements_and_keeps_their_history(client, db_session, setup):
    customer, widget, gadget, bom, cement, _ = setup
    order = _order(client, customer, [(widget, "100", "100"), (gadget, "25", "50")])
    before = _inventory_counts(db_session)
    response = client.post(f"/api/sales-orders/{order['id']}/cancel", json={"reason": "Customer withdrew"}, headers=_headers(client, "boss"))
    assert response.status_code == 200

    rows = {r["product_id"]: r for r in _requirements(client)}
    assert {r["status"] for r in rows.values()} == {"cancelled"}
    widget_row = rows[widget.id]
    # History kept: identity, source, quantity, unit and BOM snapshot are untouched.
    assert (widget_row["sales_order_id"], Decimal(widget_row["quantity"]), widget_row["unit_of_measure_id"], widget_row["bom_id"]) == (
        order["id"], 60, widget.unit_of_measure_id, bom.id,
    )
    assert [Decimal(c["quantity"]) for c in widget_row["components"]] == [2]
    assert widget_row["cancelled_at"] and "Customer withdrew" in widget_row["cancellation_reason"]
    assert Decimal(widget_row["outstanding_quantity"]) == 0
    assert db_session.query(ProductionRequirement).count() == 2
    assert len(_audits(db_session, PRODUCTION_REQUIREMENT_CANCELLED)) == 2
    # A cancelled requirement cannot take a BOM snapshot, and nothing moved in inventory.
    assert client.post(f"/api/production-requirements/{rows[gadget.id]['id']}/snapshot-bom", headers=_headers(client, "lead")).status_code == 409
    assert _inventory_counts(db_session) == before


def test_an_assessed_quantity_change_needs_confirmation_and_resolves_the_demand(client, db_session, setup):
    customer, widget, gadget, bom, cement, _ = setup
    order = _order(client, customer, [(widget, "100", "100")])
    [row] = _requirements(client)
    before = _inventory_counts(db_session)

    # Unconfirmed: refused as before, nothing changes.
    assert _edit(client, order, "120").status_code == 409
    assert _edit(client, order, "120", confirm=False).status_code == 409
    assert Decimal(_requirement(client, row["id"])["quantity"]) == 60

    # Increase: shortfall = 120 - 40 covered at hand-off.
    assert _edit(client, order, "120", confirm=True).status_code == 200
    assert (Decimal(_requirement(client, row["id"])["quantity"]), _requirement(client, row["id"])["status"]) == (80, "open")
    # Reduce below the allocation: the claim shrinks to 30, nothing is uncovered -> satisfied (kept).
    assert _edit(client, order, "30", confirm=True).status_code == 200
    satisfied = _requirement(client, row["id"])
    assert (satisfied["status"], Decimal(satisfied["quantity"]), Decimal(satisfied["allocated_quantity"])) == ("satisfied", 80, 30)
    # Increase again: the same requirement returns, with its original snapshot (50 - 30 allocated).
    assert _edit(client, order, "50", confirm=True).status_code == 200
    back = _requirement(client, row["id"])
    assert (back["status"], Decimal(back["quantity"]), back["bom_id"], back["satisfied_at"]) == ("open", 20, bom.id, None)
    assert [Decimal(c["quantity"]) for c in back["components"]] == [2]

    # The hand-off assessment itself is never rewritten.
    db_session.expire_all()
    fulfilment = db_session.query(SalesOrderLineFulfilment).one()
    assert (fulfilment.fg_covered_quantity, fulfilment.production_quantity) == (40, 60)
    assert db_session.query(ProductionRequirement).count() == 1
    assert "quantity 60 -> 80" in _audits(db_session, PRODUCTION_REQUIREMENT_QUANTITY_CHANGED)[0]
    assert "open -> satisfied" in _audits(db_session, PRODUCTION_REQUIREMENT_SATISFIED)[0]
    assert "satisfied -> open; quantity 80 -> 20" in _audits(db_session, PRODUCTION_REQUIREMENT_REOPENED)[0]
    assert _inventory_counts(db_session) == before


def test_a_fully_covered_line_gets_a_requirement_when_its_quantity_grows(client, db_session, setup):
    customer, _, gadget, _, _, _ = setup
    order = _order(client, customer, [(gadget, "5", "50")])
    assert _requirements(client) == []
    assert _edit(client, order, "12", price="50", confirm=True).status_code == 200
    [row] = _requirements(client)
    # 12 - 5 covered at hand-off; no active BOM for Gadget -> flagged.
    assert (Decimal(row["quantity"]), row["status"], row["unit_of_measure_id"]) == (7, "bom_required", gadget.unit_of_measure_id)
    assert len(_audits(db_session, PRODUCTION_REQUIREMENT_CREATED)) == 1


def test_delivery_meets_the_demand_without_any_production(client, db_session, organisation, setup):
    """The requirement is demand, not a production instruction: stock from
    anywhere satisfies it, and nothing forces production to equal it."""
    customer, widget, _, _, _, warehouse = setup
    order = _order(client, customer, [(widget, "100", "100")])
    # Stock arrives after hand-off (from anywhere -- not production).
    _stock(db_session, organisation, widget, warehouse, "100", 3)
    [row] = _requirements(client)
    wh = _headers(client, "warehouse")

    def deliver(quantity):
        body = {"sales_order_id": order["id"], "lines": [{"sales_order_line_id": order["lines"][0]["id"], "quantity": quantity}]}
        instruction = client.post("/api/delivery-instructions", json=body, headers=wh).json()
        client.patch(f"/api/delivery-instructions/{instruction['id']}/lines/{instruction['lines'][0]['id']}", json={"pallet_count": 1}, headers=wh)
        assert client.post(f"/api/delivery-instructions/{instruction['id']}/fulfil", headers=wh).status_code == 200

    # 50 delivered: the 40 allocated plus 10 free; 50 still uncovered.
    deliver("50")
    partial = _requirement(client, row["id"])
    assert [partial["status"]] + [Decimal(partial[k]) for k in ("quantity", "allocated_quantity", "outstanding_quantity")] == ["open", 50, 0, 50]
    deliver("50")
    done = _requirement(client, row["id"])
    assert (done["status"], Decimal(done["outstanding_quantity"])) == ("satisfied", 0)
    assert done["satisfied_at"] and len(_audits(db_session, PRODUCTION_REQUIREMENT_SATISFIED)) == 1
    # Cancelling a completed order is refused anyway; the record stays satisfied.
    assert client.post(f"/api/sales-orders/{order['id']}/cancel", json={"reason": "x"}, headers=_headers(client, "boss")).status_code == 409
    assert _requirement(client, row["id"])["status"] == "satisfied"
