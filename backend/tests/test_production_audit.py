"""Production audit (P0-P7): the complete chain, end to end, with every
quantity reconciled at each step --

  demand -> Production Requirement -> MRP -> Plan -> Schedule -> Order ->
  Execution -> Raw Material + FG Inventory -> Allocation -> Delivery

-- plus independent production, over-production, atomic failure and
retry, duplicate protection, cancellation at each stage and permissions.
Also the regressions for the defects found in the audit: MRP counting
already-produced plan quantity as still planned, and a retried
allocation being applied twice."""

from decimal import Decimal
from types import SimpleNamespace

from app.models.fg_allocation import FgAllocation
from app.models.finished_goods_inventory import FinishedGoodsInventory, FinishedGoodsMovement
from app.models.inventory import RawMaterialInventory, StockMovement
from app.models.production_execution import ProductionExecution
from app.models.production_order import ProductionOrder
from app.models.production_requirement import ProductionRequirement
from app.models.sales_order import SalesOrder
from tests.test_production_execution import MON, _headers, _receive, _record, setup  # noqa: F401 -- shared fixture


def _warehouse_id(db_session):
    return SimpleNamespace(id=db_session.query(RawMaterialInventory.warehouse_id).first()[0])


def _rm(db_session, material):
    db_session.expire_all()
    return db_session.query(RawMaterialInventory.quantity_on_hand).filter(RawMaterialInventory.raw_material_id == material.id).scalar()


def _fg(client, product):
    body = client.get(f"/api/fg-allocations/products/{product.id}", headers=_headers(client, "boss")).json()
    return tuple(Decimal(body[k]) for k in ("on_hand_quantity", "allocated_quantity", "free_quantity"))


def _requirement(db_session):
    db_session.expire_all()
    r = db_session.query(ProductionRequirement).one()
    return r.status, r.quantity


def _mrp_row(client, requirement_id):
    rows = client.get("/api/mrp", headers=_headers(client, "planner")).json()["rows"]
    row = next(r for r in rows if r["production_requirement_id"] == requirement_id)
    return row, [Decimal(row[k]) for k in ("outstanding_quantity", "planned_quantity", "proposed_quantity")]


def _order(client, order):
    body = client.get(f"/api/production-orders/{order['id']}", headers=_headers(client, "operator")).json()
    return body["status"], Decimal(body["produced_quantity"]), Decimal(body["remaining_quantity"])


def _allocate(client, sales_order, quantity, reference=None):
    body = {"sales_order_line_id": sales_order["lines"][0]["id"], "quantity": quantity}
    if reference:
        body["client_reference"] = reference
    return client.post("/api/fg-allocations/allocate", json=body, headers=_headers(client, "boss"))


def _ledger(db_session):
    return (
        db_session.query(StockMovement).filter(StockMovement.movement_type == "production_issue").count(),
        db_session.query(FinishedGoodsMovement).filter(FinishedGoodsMovement.reference_type == "production_execution").count(),
        db_session.query(FinishedGoodsMovement).filter(FinishedGoodsMovement.movement_type == "delivery").count(),
    )


def test_customer_demand_end_to_end_reconciles_at_every_step(client, db_session, setup):
    _, customer_order, sales_order, m, n, widget, organisation = setup
    requirement_id = db_session.query(ProductionRequirement.id).scalar()

    # 1-4. Demand 1000, FG 100 allocated at hand-off: 900 uncovered, fully planned.
    assert _requirement(db_session) == ("open", 900)
    assert _fg(client, widget) == (100, 100, 0)
    assert _mrp_row(client, requirement_id)[1] == [900, 900, 0]
    assert _order(client, customer_order) == ("issued", 0, 900)

    # 8-11. Partial production: materials consumed from the snapshot, FG received.
    assert _record(client, customer_order, "400").status_code == 201
    assert (_rm(db_session, m), _rm(db_session, n)) == (Decimal("720"), Decimal("130"))
    assert _fg(client, widget) == (500, 100, 400)
    assert _order(client, customer_order) == ("partially_completed", 400, 500)
    # Production is supply, not fulfilment: demand unchanged; MRP plans only what is still to be produced.
    assert _requirement(db_session) == ("open", 900)
    assert _mrp_row(client, requirement_id)[1] == [900, 500, 400]

    # 14-15. The produced FG is allocated through the allocation system; a retry does not double it.
    assert _allocate(client, sales_order, "400", "alloc-1").status_code == 200
    assert _allocate(client, sales_order, "400", "alloc-1").status_code == 200
    assert _fg(client, widget) == (500, 500, 0)
    assert _requirement(db_session) == ("open", 500)
    assert _mrp_row(client, requirement_id)[1] == [500, 500, 0]

    # 12 + atomicity: 350 posts; 150 fails on N (needs 45, 25 left) and changes nothing.
    assert _record(client, customer_order, "350").status_code == 201
    before = (_rm(db_session, m), _rm(db_session, n), _fg(client, widget), _ledger(db_session), db_session.query(ProductionExecution).count())
    short = _record(client, customer_order, "150")
    assert short.status_code == 400 and "N: needs 45, 25 on hand" in short.json()["error"]["message"]
    assert (_rm(db_session, m), _rm(db_session, n), _fg(client, widget), _ledger(db_session), db_session.query(ProductionExecution).count()) == before
    assert _order(client, customer_order) == ("partially_completed", 750, 150)
    # Restore material; the retry succeeds and completes exactly at the planned quantity.
    _receive(db_session, organisation, n, _warehouse_id(db_session), "100", 50)
    assert _record(client, customer_order, "150").status_code == 201
    assert _order(client, customer_order) == ("completed", 900, 0)
    executions = db_session.query(ProductionExecution).filter(ProductionExecution.production_order_id == customer_order["id"]).all()
    assert sorted(e.produced_quantity for e in executions) == [Decimal("150"), Decimal("350"), Decimal("400")]
    assert _ledger(db_session) == (6, 3, 0)  # 3 executions x 2 materials; 3 FG receipts; no duplicates
    assert (_rm(db_session, m), _rm(db_session, n)) == (Decimal("1000") - Decimal("630"), Decimal("250") - Decimal("270") + Decimal("100"))

    # 15-16. Allocate the rest -> requirement satisfied; delivery consumes this order's allocation.
    assert _allocate(client, sales_order, "500").status_code == 200
    assert _requirement(db_session) == ("satisfied", 500)
    assert _fg(client, widget) == (1000, 1000, 0)
    boss = _headers(client, "boss")
    body = {"sales_order_id": sales_order["id"], "lines": [{"sales_order_line_id": sales_order["lines"][0]["id"], "quantity": "1000"}]}
    instruction = client.post("/api/delivery-instructions", json=body, headers=boss).json()
    client.patch(f"/api/delivery-instructions/{instruction['id']}/lines/{instruction['lines'][0]['id']}", json={"pallet_count": 1}, headers=boss)
    assert client.post(f"/api/delivery-instructions/{instruction['id']}/fulfil", headers=boss).status_code == 200
    assert client.post(f"/api/delivery-instructions/{instruction['id']}/fulfil", headers=boss).status_code == 409  # never twice
    assert _fg(client, widget) == (0, 0, 0)

    # 17. Sales Order delivery figures.
    order = client.get(f"/api/sales-orders/{sales_order['id']}", headers=boss).json()
    line = order["lines"][0]
    assert (order["status"], *[Decimal(line[k]) for k in ("quantity", "fulfilled_quantity", "remaining_quantity", "allocated_quantity")]) == (
        "completed", 1000, 1000, 0, 0,
    )
    assert _ledger(db_session) == (6, 3, 1)


def test_independent_production_and_over_production_leave_demand_alone(client, db_session, setup):
    independent, customer_order, sales_order, m, n, widget, organisation = setup
    _receive(db_session, organisation, m, _warehouse_id(db_session), "2000", 51)
    _receive(db_session, organisation, n, _warehouse_id(db_session), "2000", 52)
    so_before = client.get(f"/api/sales-orders/{sales_order['id']}", headers=_headers(client, "boss")).json()

    # Independent production: no Sales Order, customer or requirement involved; output is free FG.
    assert _record(client, independent, "1000").status_code == 201
    assert _order(client, independent) == ("completed", 1000, 0)
    assert _fg(client, widget) == (1100, 100, 1000)
    assert _requirement(db_session) == ("open", 900)
    # Fully produced independent plans leave MRP's "what to produce" list.
    assert not any(r["demand_type"] == "independent" for r in client.get("/api/mrp", headers=_headers(client, "planner")).json()["rows"])

    # Over-production against demand (900 + 1000 produced for 900 demand): demand untouched,
    # 900 may be allocated, the excess stays free; no fake demand; order quantity unchanged.
    assert _record(client, customer_order, "900").status_code == 201
    assert _allocate(client, sales_order, "900").status_code == 200
    assert _requirement(db_session) == ("satisfied", 900)
    assert _fg(client, widget) == (2000, 1000, 1000)
    assert db_session.query(ProductionRequirement).count() == 1
    so_after = client.get(f"/api/sales-orders/{sales_order['id']}", headers=_headers(client, "boss")).json()
    assert so_after["lines"][0]["quantity"] == so_before["lines"][0]["quantity"]
    # A Production Order itself never exceeds its issued quantity.
    assert _record(client, independent, "1").status_code == 409


def test_cancellation_at_each_stage_releases_only_what_it_should(client, db_session, setup):
    independent, customer_order, sales_order, _, _, widget, _ = setup
    planner = _headers(client, "planner")
    movements = (db_session.query(StockMovement).count(), db_session.query(FinishedGoodsMovement).count())

    # Plan before scheduling.
    plan = client.post("/api/production-plans", json={"source_type": "independent", "product_id": widget.id, "planned_quantity": "10"}, headers=planner).json()
    assert client.post(f"/api/production-plans/{plan['id']}/cancel", json={"reason": "No longer needed"}, headers=planner).json()["status"] == "cancelled"
    # Schedule entry before any order: the plan stays planned.
    plan = client.post("/api/production-plans", json={"source_type": "independent", "product_id": widget.id, "planned_quantity": "10"}, headers=planner).json()
    client.post(f"/api/production-plans/{plan['id']}/plan", headers=planner)
    entry = client.post("/api/production-schedule", json={"production_plan_id": plan["id"], "scheduled_date": MON, "quantity": "10"}, headers=planner).json()
    assert client.post(f"/api/production-schedule/{entry['id']}/cancel", json={"reason": "Moved"}, headers=planner).json()["status"] == "cancelled"
    assert client.get(f"/api/production-plans/{plan['id']}", headers=planner).json()["status"] == "planned"
    # Draft order, and issued order before execution.
    entry = client.post("/api/production-schedule", json={"production_plan_id": plan["id"], "scheduled_date": MON, "quantity": "10"}, headers=planner).json()
    draft = client.post("/api/production-orders", json={"production_schedule_entry_id": entry["id"]}, headers=planner).json()
    assert client.post(f"/api/production-orders/{draft['id']}/cancel", json={"reason": "Typo"}, headers=planner).json()["status"] == "cancelled"
    assert client.post(f"/api/production-orders/{independent['id']}/cancel", json={"reason": "Re-plan"}, headers=planner).json()["status"] == "cancelled"

    # Sales Order with allocation and requirement: both released/cancelled; production is not touched.
    boss = _headers(client, "boss")
    assert client.post(f"/api/sales-orders/{sales_order['id']}/cancel", json={"reason": "Lost"}, headers=boss).status_code == 200
    db_session.expire_all()
    assert _requirement(db_session) == ("cancelled", 900)
    assert [a.quantity for a in db_session.query(FgAllocation)] == [0]
    assert db_session.get(ProductionOrder, customer_order["id"]).status == "issued"
    assert db_session.get(SalesOrder, sales_order["id"]).status == "cancelled"
    # No inventory movement from any cancellation.
    assert (db_session.query(StockMovement).count(), db_session.query(FinishedGoodsMovement).count()) == movements
    # A completed physical event cannot be undone by a status change.
    assert _record(client, customer_order, "10").status_code == 201
    assert client.post(f"/api/production-orders/{customer_order['id']}/cancel", json={"reason": "x"}, headers=planner).status_code == 409


def test_production_endpoints_refuse_users_without_production_rights(client, db_session, setup):
    independent, _, _, _, _, widget, _ = setup
    order_id = independent["id"]
    plan_id = independent["production_plan_id"] if "production_plan_id" in independent else db_session.get(ProductionOrder, order_id).production_plan_id
    reads = [
        "/api/mrp", "/api/production-plans", f"/api/production-plans/{plan_id}", f"/api/production-plans/{plan_id}/schedule",
        "/api/production-requirements", f"/api/production-schedule/days?start={MON}&end={MON}", "/api/production-orders",
        f"/api/production-orders/{order_id}", f"/api/production-status/day?date={MON}",
    ]
    writes = [
        ("post", "/api/production-plans", {"source_type": "independent", "product_id": widget.id, "planned_quantity": "1"}),
        ("post", f"/api/production-plans/{plan_id}/cancel", {"reason": "x"}),
        ("post", "/api/production-schedule", {"production_plan_id": plan_id, "scheduled_date": MON, "quantity": "1"}),
        ("post", f"/api/production-orders/{order_id}/cancel", {"reason": "x"}),
        ("post", f"/api/production-orders/{order_id}/start", None),
        ("post", f"/api/production-orders/{order_id}/executions", {"produced_quantity": "1"}),
    ]
    salesman = _headers(client, "salesman_a")
    for url in reads:
        assert client.get(url, headers=salesman).status_code == 403, url
    for method, url, body in writes:
        assert getattr(client, method)(url, json=body, headers=salesman).status_code == 403, url
    # The operator (view + execute) cannot plan, schedule or cancel.
    operator = _headers(client, "operator")
    for method, url, body in writes[:4]:
        assert getattr(client, method)(url, json=body, headers=operator).status_code == 403, url
    # The planner (view + manage) cannot record production.
    assert client.post(f"/api/production-orders/{order_id}/executions", json={"produced_quantity": "1"}, headers=_headers(client, "planner")).status_code == 403
    assert db_session.query(ProductionExecution).count() == 0
