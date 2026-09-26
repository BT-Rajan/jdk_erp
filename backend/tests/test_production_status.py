"""P7 -- Production Status: what is planned, what is happening, what was
produced -- read-only, derived from Production Orders, their schedule
entries and posted executions. Production is posted only through P6's
Record Production."""

from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

from app.core.security import hash_password
from app.core.timezone import JDK_TIMEZONE
from app.models.finished_goods_inventory import FinishedGoodsMovement
from app.models.inventory import RawMaterialInventory, StockMovement
from app.models.machine import Machine
from app.models.production_execution import ProductionExecution
from app.models.user import User
from app.models.user_permission import UserPermission
from app.services import fg_allocation_service
from tests.test_production_execution import MON, _headers, _receive, _record, setup  # noqa: F401 -- shared fixture

TUE, NEXT_WEEK = "2026-09-29", "2026-10-06"


def _today(monkeypatch, iso):
    moment = datetime.fromisoformat(f"{iso}T09:00:00").replace(tzinfo=JDK_TIMEZONE)
    monkeypatch.setattr("app.services.production_status_service.now_jdk", lambda: moment)
    monkeypatch.setattr("app.api.production_status.now_jdk", lambda: moment)


def _day(client, iso=None, username="operator"):
    params = {"date": iso} if iso else {}
    response = client.get("/api/production-status/day", params=params, headers=_headers(client, username))
    assert response.status_code == 200, response.json()
    return response.json()


def _row(day, order):
    return next(r for r in day["orders"] if r["production_order_id"] == order["id"])


def _counts(day):
    return [day[k] for k in ("order_count", "completed_count", "in_progress_count", "not_started_count", "cancelled_count")]


def _ledger(db_session):
    return db_session.query(StockMovement).count(), db_session.query(FinishedGoodsMovement).count()


def test_today_shows_the_scheduled_orders_and_totals_follow_actual_production(client, db_session, setup, monkeypatch):
    independent, customer_order, sales_order, m, n, widget, organisation = setup
    _today(monkeypatch, MON)
    before = _ledger(db_session)
    day = _day(client)  # today by default
    assert (day["date"], day["is_working_day"], day["previous_working_day"], day["next_working_day"]) == (MON, True, "2026-09-27", TUE)
    assert [r["order_number"] for r in day["orders"]] == [independent["order_number"], customer_order["order_number"]]
    assert [r["sequence"] for r in day["orders"]] == [1, 2]
    ind, cust = _row(day, independent), _row(day, customer_order)
    assert [Decimal(ind[k]) for k in ("planned_quantity", "produced_quantity", "remaining_quantity")] == [1000, 0, 1000]
    assert (ind["status"], ind["source_type"], ind["sales_order_number"], ind["production_line_name"]) == ("issued", "independent", None, "Production Line 1")
    assert (cust["sales_order_number"], cust["sales_order_line_number"], cust["required_by_date"]) == (sales_order["order_number"], 1, "2026-10-05")
    assert _counts(day) == [2, 0, 0, 2, 0]
    [totals] = day["totals"]
    assert [Decimal(totals[k]) for k in ("scheduled_quantity", "produced_quantity", "remaining_quantity")] == [1900, 0, 1900]
    # Viewing changes nothing.
    assert _ledger(db_session) == before

    # Partial production: the status and quantities come from the execution.
    assert _record(client, independent, "600").status_code == 201
    day = _day(client, MON)
    ind = _row(day, independent)
    assert (ind["status"], *[Decimal(ind[k]) for k in ("produced_quantity", "remaining_quantity")]) == ("partially_completed", 600, 400)
    assert _counts(day) == [2, 0, 1, 1, 0]
    assert [Decimal(day["totals"][0][k]) for k in ("produced_quantity", "remaining_quantity")] == [600, 1300]
    # N is now short for what remains (400 needs 120 of 70; the customer order's 900 needs 270).
    assert "material_shortage" in ind["exceptions"] and "material_shortage" in _row(day, customer_order)["exceptions"]

    # Completion, and a cancelled order listed apart and kept out of the totals.
    _receive(db_session, organisation, n, SimpleNamespace(id=db_session.query(RawMaterialInventory.warehouse_id).first()[0]), "100", 3)
    assert _record(client, independent, "400").status_code == 201
    client.post(f"/api/production-orders/{customer_order['id']}/cancel", json={"reason": "Re-planned"}, headers=_headers(client, "planner"))
    day = _day(client, MON)
    assert _counts(day) == [1, 1, 0, 0, 1]
    assert (_row(day, independent)["status"], _row(day, customer_order)["status"]) == ("completed", "cancelled")
    assert _row(day, customer_order)["exceptions"] == ["cancelled"] and day["orders"][-1]["production_order_id"] == customer_order["id"]
    assert [Decimal(day["totals"][0][k]) for k in ("scheduled_quantity", "produced_quantity", "remaining_quantity")] == [1000, 1000, 0]

    # The day reconciles with the order detail and its execution history.
    detail = client.get(f"/api/production-orders/{independent['id']}", headers=_headers(client, "operator")).json()
    assert Decimal(detail["produced_quantity"]) == sum(Decimal(e["produced_quantity"]) for e in detail["executions"]) == 1000
    # FG shown on the detail is Inventory's own figure.
    on_hand, _, free = fg_allocation_service.product_position(db_session, organisation.id, widget.id)
    assert (Decimal(detail["fg_on_hand_quantity"]), Decimal(detail["fg_free_quantity"])) == (on_hand, free)


def test_past_days_stay_viewable_with_their_exceptions(client, db_session, setup, monkeypatch):
    independent, customer_order, _, _, _, _, _ = setup
    assert _record(client, independent, "600").status_code == 201
    _today(monkeypatch, TUE)
    monday = _day(client, MON)
    assert monday["date"] == MON and _counts(monday) == [2, 0, 1, 1, 0]
    assert "not_produced" in _row(monday, independent)["exceptions"]  # yesterday, 400 still to do
    assert "overdue" not in _row(monday, customer_order)["exceptions"]  # required 5 Oct
    _today(monkeypatch, NEXT_WEEK)
    late = _row(_day(client, MON), customer_order)
    assert {"not_produced", "overdue"} <= set(late["exceptions"])
    # An empty, non-working day.
    friday = _day(client, "2026-10-02")
    assert (friday["is_working_day"], friday["orders"], friday["next_working_day"]) == (False, [], "2026-10-04")
    # History is what was posted: the executions are unchanged by viewing.
    assert db_session.query(ProductionExecution).count() == 1


def test_order_filters_and_permissions(client, db_session, setup, organisation):
    independent, customer_order, _, _, _, widget, _ = setup
    operator = _headers(client, "operator")

    def numbers(**params):
        response = client.get("/api/production-orders", params=params, headers=operator)
        assert response.status_code == 200, response.json()
        return sorted(o["order_number"] for o in response.json())

    both = sorted([independent["order_number"], customer_order["order_number"]])
    assert numbers(product_id=widget.id) == both
    assert numbers(q=independent["order_number"]) == [independent["order_number"]]
    assert numbers(status="issued", date_from=MON, date_to=MON) == both
    machine_line = db_session.query(Machine.production_line_id).scalar()
    assert numbers(production_line_id=machine_line) == both
    assert numbers(production_line_id=machine_line + 999) == []

    # Execute-only users see the production screens; others do not.
    floor = User(
        organisation_id=organisation.id, role="team_member", full_name="Floor", email="floor@example.com",
        username="floor", password_hash=hash_password("Str0ng!Pass"), is_active=True,
    )
    db_session.add(floor)
    db_session.flush()
    db_session.add(UserPermission(organisation_id=organisation.id, user_id=floor.id, module_key="production", action="execute", scope="all"))
    db_session.commit()
    assert client.get("/api/production-status/day", params={"date": MON}, headers=_headers(client, "floor")).status_code == 200
    assert client.get(f"/api/production-orders/{independent['id']}", headers=_headers(client, "floor")).status_code == 200
    assert client.get("/api/production-status/day", headers=_headers(client, "salesman_a")).status_code == 403
