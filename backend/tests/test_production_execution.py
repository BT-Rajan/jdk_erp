"""P6 -- Production Execution: what actually happened during production.

Recording production on an executable Production Order consumes raw
materials from the order's frozen BOM snapshot (PRODUCTION_ISSUE, via the
Raw Material single writer) and receives the actual output into Finished
Goods (PRODUCTION_COMPLETION, via the FG single writer) in one atomic
transaction. Partial production, no overproduction, no duplicates, never
assigned to a customer."""

from datetime import datetime
from types import SimpleNamespace
from decimal import Decimal

import pytest

from app.api import quotations as quotations_api
from app.api import sales_orders as sales_orders_api
from app.core.roles import ADMIN, MANAGER, TEAM_MEMBER
from app.core.security import hash_password
from app.core.timezone import JDK_TIMEZONE
from app.models.audit_event import PRODUCTION_RECORDED, AuditEvent
from app.models.bom import ACTIVE, Bom, BomComponent
from app.models.customer import Customer
from app.models.fg_allocation import FgAllocation
from app.models.finished_goods_inventory import FinishedGoodsInventory, FinishedGoodsMovement
from app.models.inventory import RawMaterialInventory, StockMovement
from app.models.production_execution import ProductionExecution
from app.models.production_requirement import ProductionRequirement
from app.models.raw_material import RawMaterial
from app.models.role_permission import RolePermission
from app.models.unit import UnitOfMeasure
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
MON = "2026-09-28"


def _headers(client, username):
    login = client.post("/api/auth/login", json={"username": username, "password": "Str0ng!Pass"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _receive(db_session, organisation, material, warehouse, quantity, reference_id):
    inventory_service.receive_stock(
        db_session, organisation_id=organisation.id, raw_material_id=material.id, warehouse_id=warehouse.id,
        quantity=Decimal(quantity), unit_of_measure_id=material.unit_of_measure_id, reference_type="test_seed",
        reference_id=reference_id, created_by_user_id=None,
    )
    db_session.commit()


@pytest.fixture()
def setup(client, db_session, organisation, electronics_category, widget_product, cement_raw_material, warehouse_1, machine_1, monkeypatch):
    """BOM: 1000 kg Widget <- 700 kg M (Cement) + 300 kg N. Stock: M 1000,
    N 250. An issued order for 1000 (independent plan, Monday); a customer
    order for 1000 Widgets (100 FG on hand, allocated) with an issued
    order for its 900 shortfall. `operator` executes, `planner` manages."""
    for module in (working_calendar_service, quotations_api, sales_orders_api, feasibility_record_service, quotation_readiness_service):
        monkeypatch.setattr(module, "now_jdk", lambda: MONDAY_9AM_KUWAIT)
    users = {}
    for username, role in (("salesman_a", TEAM_MEMBER), ("boss", ADMIN), ("planner", MANAGER), ("operator", TEAM_MEMBER)):
        users[username] = User(
            organisation_id=organisation.id, role=role, full_name=username.title(), email=f"{username}@example.com",
            username=username, password_hash=hash_password("Str0ng!Pass"), is_active=True,
        )
        db_session.add(users[username])
    db_session.flush()
    for action in ("view", "manage"):
        db_session.add(RolePermission(organisation_id=organisation.id, role=MANAGER, module_key="production", action=action, scope="all"))
    for action in ("view", "execute"):
        db_session.add(UserPermission(organisation_id=organisation.id, user_id=users["operator"].id, module_key="production", action=action, scope="all"))
    n_material = RawMaterial(
        organisation_id=organisation.id, code="RM002", name="N", category_id=electronics_category.id,
        unit_of_measure_id=cement_raw_material.unit_of_measure_id, is_active=True,
    )
    customer = Customer(
        organisation_id=organisation.id, code="300001", name="A Co", assigned_to_user_id=users["salesman_a"].id,
        phone="96511111111", address="Shuwaikh", payment_arrangement="after_delivery",
    )
    widget_product.min_selling_price, widget_product.max_selling_price = Decimal("90"), Decimal("110")
    organisation.production_hours_per_day = Decimal("8")
    machine_1.capacity_quantity, machine_1.capacity_period_hours = Decimal("5000"), Decimal("8")
    db_session.add_all([n_material, customer])
    db_session.flush()
    bom = Bom(organisation_id=organisation.id, product_id=widget_product.id, base_quantity=Decimal("1000"), status=ACTIVE)
    db_session.add(bom)
    db_session.flush()
    db_session.add_all([
        BomComponent(bom_id=bom.id, raw_material_id=cement_raw_material.id, quantity=Decimal("700")),
        BomComponent(bom_id=bom.id, raw_material_id=n_material.id, quantity=Decimal("300")),
    ])
    db_session.commit()
    _receive(db_session, organisation, cement_raw_material, warehouse_1, "1000", 1)
    _receive(db_session, organisation, n_material, warehouse_1, "250", 2)
    finished_goods_inventory_service.receive_finished_goods(
        db_session, organisation_id=organisation.id, product_id=widget_product.id, warehouse_id=warehouse_1.id,
        quantity=Decimal("100"), unit_of_measure_id=widget_product.unit_of_measure_id, reference_type="test_seed",
        reference_id=1, created_by_user_id=None,
    )
    db_session.commit()

    a, planner = _headers(client, "salesman_a"), _headers(client, "planner")
    line = {"product_id": widget_product.id, "quantity": "1000", "unit_of_measure_id": widget_product.unit_of_measure_id, "unit_price": "100"}
    quotation = client.post("/api/quotations", json={"customer_id": customer.id, "requested_delivery_date": "2026-10-05", "lines": [line]}, headers=a).json()
    client.post(f"/api/quotations/{quotation['id']}/accept", headers=a)
    sales_order = client.post(f"/api/quotations/{quotation['id']}/convert", headers=a).json()
    requirement_id = db_session.query(ProductionRequirement.id).scalar()

    def issued_order(plan_body, quantity):
        plan = client.post("/api/production-plans", json=plan_body, headers=planner).json()
        client.post(f"/api/production-plans/{plan['id']}/plan", headers=planner)
        entry = client.post("/api/production-schedule", json={"production_plan_id": plan["id"], "scheduled_date": MON, "quantity": quantity}, headers=planner).json()
        order = client.post("/api/production-orders", json={"production_schedule_entry_id": entry["id"]}, headers=planner).json()
        assert client.post(f"/api/production-orders/{order['id']}/issue", headers=planner).status_code == 200
        return order

    independent = issued_order({"source_type": "independent", "product_id": widget_product.id, "planned_quantity": "1000"}, "1000")
    customer_order = issued_order({"source_type": "customer_demand", "production_requirement_id": requirement_id}, "900")
    return independent, customer_order, sales_order, cement_raw_material, n_material, widget_product, organisation


def _record(client, order, quantity, username="operator", **extra):
    body = {"produced_quantity": quantity, **extra}
    return client.post(f"/api/production-orders/{order['id']}/executions", json=body, headers=_headers(client, username))


def _order(client, order):
    return client.get(f"/api/production-orders/{order['id']}", headers=_headers(client, "operator")).json()


def _stock(db_session, product, *materials):
    db_session.expire_all()
    fg = db_session.query(FinishedGoodsInventory.quantity_on_hand).filter(FinishedGoodsInventory.product_id == product.id).scalar()
    rm = [
        db_session.query(RawMaterialInventory.quantity_on_hand).filter(RawMaterialInventory.raw_material_id == m.id).scalar()
        for m in materials
    ]
    return [fg, *rm], db_session.query(StockMovement).count(), db_session.query(FinishedGoodsMovement).count()


def _q(body, *keys):
    return [Decimal(body[k]) for k in keys]


def test_partial_then_complete_production_consumes_from_the_snapshot_and_receives_fg(client, db_session, setup):
    independent, _, _, m, n, widget, organisation = setup
    # The master BOM changing after issue never reaches the order.
    db_session.query(BomComponent).filter(BomComponent.raw_material_id == m.id).update({BomComponent.quantity: Decimal("999")})
    db_session.commit()
    (fg, m_on_hand, n_on_hand), stock_moves, fg_moves = _stock(db_session, widget, m, n)
    assert (fg, m_on_hand, n_on_hand) == (100, 1000, 250)

    first = _record(client, independent, "600")
    assert first.status_code == 201, first.json()
    body = first.json()
    assert (body["status"], *_q(body, "quantity", "produced_quantity", "remaining_quantity")) == ("partially_completed", 1000, 600, 400)
    [execution] = body["executions"]
    assert (execution["sequence"], Decimal(execution["produced_quantity"]), execution["fg_movement_id"] is not None) == (1, 600, True)
    # 700 x 600 / 1000 = 420 of M; 300 x 600 / 1000 = 180 of N -- in their own unit.
    assert {(x["raw_material_id"], Decimal(x["quantity"]), x["unit_of_measure_id"]) for x in execution["materials"]} == {
        (m.id, 420, m.unit_of_measure_id), (n.id, 180, n.unit_of_measure_id),
    }
    (fg, m_on_hand, n_on_hand), new_stock_moves, new_fg_moves = _stock(db_session, widget, m, n)
    assert (fg, m_on_hand, n_on_hand, new_stock_moves - stock_moves, new_fg_moves - fg_moves) == (700, 580, 70, 2, 1)
    moves = db_session.query(StockMovement).filter(StockMovement.movement_type == "production_issue").all()
    assert sorted(mv.quantity for mv in moves) == [Decimal("-420"), Decimal("-180")]
    assert {mv.reference_type for mv in moves} == {"production_execution_material"}
    fg_move = db_session.query(FinishedGoodsMovement).filter(FinishedGoodsMovement.reference_type == "production_execution").one()
    assert (fg_move.quantity, fg_move.movement_type, fg_move.unit_of_measure_id) == (Decimal("600"), "production_completion", widget.unit_of_measure_id)

    # Overproduction is refused, never clamped.
    over = _record(client, independent, "401")
    assert over.status_code == 409 and "Only 400 remains" in over.json()["error"]["message"]

    # Not enough N for 400 (needs 120, 70 on hand): nothing at all is posted.
    before = _stock(db_session, widget, m, n)
    short = _record(client, independent, "400")
    assert short.status_code == 400 and "N: needs 120, 70 on hand" in short.json()["error"]["message"]
    assert _stock(db_session, widget, m, n) == before
    assert (_order(client, independent)["status"], Decimal(_order(client, independent)["produced_quantity"])) == ("partially_completed", 600)
    assert db_session.query(ProductionExecution).count() == 1

    _receive(db_session, organisation, n, SimpleNamespace(id=db_session.query(RawMaterialInventory.warehouse_id).first()[0]), "100", 3)
    done = _record(client, independent, "400").json()
    assert (done["status"], *_q(done, "produced_quantity", "remaining_quantity")) == ("completed", 1000, 0)
    assert [e["sequence"] for e in done["executions"]] == [1, 2]
    assert sum(Decimal(e["produced_quantity"]) for e in done["executions"]) == Decimal(done["produced_quantity"])
    assert {c["raw_material_id"]: Decimal(c["consumed_quantity"]) for c in done["components"]} == {m.id: 700, n.id: 300}
    (fg, m_on_hand, n_on_hand), _, _ = _stock(db_session, widget, m, n)
    assert (fg, m_on_hand, n_on_hand) == (1100, 300, 50)
    # Completed: never executed again, never cancelled.
    assert _record(client, independent, "1").status_code == 409
    assert client.post(f"/api/production-orders/{independent['id']}/cancel", json={"reason": "x"}, headers=_headers(client, "planner")).status_code == 409
    assert db_session.query(AuditEvent).filter(AuditEvent.action == PRODUCTION_RECORDED).count() == 2


def test_retry_never_posts_twice_but_separate_executions_are_allowed(client, db_session, setup):
    independent, _, _, m, n, widget, _ = setup
    first = _record(client, independent, "100", client_reference="submit-1")
    assert first.status_code == 201
    before = _stock(db_session, widget, m, n)
    retry = _record(client, independent, "100", client_reference="submit-1")
    assert retry.status_code == 200 and len(retry.json()["executions"]) == 1
    assert _stock(db_session, widget, m, n) == before
    # The same reference for a different record is refused.
    assert _record(client, independent, "50", client_reference="submit-1").status_code == 409
    # A separate, legitimate execution.
    second = _record(client, independent, "100", client_reference="submit-2").json()
    assert (len(second["executions"]), Decimal(second["produced_quantity"])) == (2, 200)


def test_production_is_supply_not_customer_fulfilment(client, db_session, setup):
    _, customer_order, sales_order, m, n, widget, organisation = setup
    requirement = db_session.query(ProductionRequirement).one()
    before = (requirement.status, requirement.quantity, [a.quantity for a in db_session.query(FgAllocation)])
    assert _record(client, customer_order, "300").status_code == 201
    db_session.expire_all()
    requirement = db_session.query(ProductionRequirement).one()
    # Requirement and allocation untouched; the 300 is free FG, not the customer's.
    assert (requirement.status, requirement.quantity, [a.quantity for a in db_session.query(FgAllocation)]) == before
    position = client.get(f"/api/fg-allocations/products/{widget.id}", headers=_headers(client, "boss")).json()
    assert [Decimal(position[k]) for k in ("on_hand_quantity", "allocated_quantity", "free_quantity")] == [400, 100, 300]
    line = client.get(f"/api/sales-orders/{sales_order['id']}", headers=_headers(client, "boss")).json()["lines"][0]
    assert (Decimal(line["fulfilled_quantity"]), Decimal(line["allocated_quantity"])) == (0, 100)


def test_state_rules_cancellation_uom_and_permissions(client, db_session, setup):
    independent, customer_order, _, m, n, widget, _ = setup
    planner, operator = _headers(client, "planner"), _headers(client, "operator")
    # Only the execute grant records or starts production.
    assert _record(client, independent, "10", username="planner").status_code == 403
    assert client.post(f"/api/production-orders/{independent['id']}/start", headers=planner).status_code == 403
    started = client.post(f"/api/production-orders/{independent['id']}/start", headers=operator).json()
    assert (started["status"], started["started_at"] is not None) == ("in_progress", True)
    assert client.post(f"/api/production-orders/{independent['id']}/start", headers=operator).status_code == 409
    # Started but nothing produced: may still be cancelled; cancelled cannot execute.
    cancelled = client.post(f"/api/production-orders/{independent['id']}/cancel", json={"reason": "Wrong line"}, headers=planner)
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    assert _record(client, independent, "10").status_code == 409

    # A raw material whose unit changed since issue: refused, nothing posted or converted.
    before = _stock(db_session, widget, m, n)
    other = db_session.query(RawMaterial).filter(RawMaterial.id == n.id).one()
    original_unit = other.unit_of_measure_id
    tonne = UnitOfMeasure(organisation_id=other.organisation_id, name="Tonne X", code="TX", is_active=True)
    db_session.add(tonne)
    db_session.flush()
    other.unit_of_measure_id = tonne.id
    db_session.commit()
    refused = _record(client, customer_order, "10")
    assert refused.status_code == 409 and "differs from the order's BOM snapshot" in refused.json()["error"]["message"]
    assert _stock(db_session, widget, m, n) == before
    other.unit_of_measure_id = original_unit
    db_session.commit()

    # History cannot be edited or deleted: there is no such route.
    posted = _record(client, customer_order, "10").json()
    execution_id = posted["executions"][0]["id"]
    for method in (client.patch, client.put, client.delete):
        assert method(f"/api/production-orders/{customer_order['id']}/executions/{execution_id}", headers=planner).status_code in (404, 405)
    # Produced quantity always reconciles with execution history.
    assert Decimal(_order(client, customer_order)["produced_quantity"]) == sum(
        e.produced_quantity for e in db_session.query(ProductionExecution).filter(ProductionExecution.production_order_id == customer_order["id"])
    )
