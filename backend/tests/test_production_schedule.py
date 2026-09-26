"""P4 -- Production Scheduling: when accepted Production Plans will be
produced. Entries on working days (existing calendar) on the machine, in
sequence, never totalling more than the plan; required-by never moved and
late entries flagged; daily capacity = machine rate x production hours
per day. No inventory, no Production Order, no change to demand."""

from datetime import date, datetime
from decimal import Decimal

import pytest

from app.api import quotations as quotations_api
from app.api import sales_orders as sales_orders_api
from app.core.database import Base
from app.core.roles import ADMIN, MANAGER, TEAM_MEMBER
from app.core.security import hash_password
from app.core.timezone import JDK_TIMEZONE
from app.models.audit_event import PRODUCTION_RESCHEDULED, PRODUCTION_SCHEDULE_CANCELLED, PRODUCTION_SCHEDULED, AuditEvent
from app.models.bom import ACTIVE, Bom, BomComponent
from app.models.customer import Customer
from app.models.finished_goods_inventory import FinishedGoodsInventory, FinishedGoodsMovement
from app.models.inventory import RawMaterialInventory, StockMovement
from app.models.organisation import Organisation
from app.models.organisation_holiday import OrganisationHoliday
from app.models.production_requirement import ProductionRequirement
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
MON, TUE, WED, THU, FRI = "2026-09-28", "2026-09-29", "2026-09-30", "2026-10-01", "2026-10-02"


def _headers(client, username):
    login = client.post("/api/auth/login", json={"username": username, "password": "Str0ng!Pass"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.fixture()
def setup(client, db_session, organisation, widget_product, cement_raw_material, warehouse_1, machine_1, monkeypatch):
    """Widget (kg): 600 on hand, BOM 1 <- 2 Cement. Machine: 500 kg per 8 h;
    8 production hours per day -> 500 kg/day. Wednesday is a holiday.
    A customer order for 1000 (600 allocated, 400 to produce, required by
    Monday 5 Oct) with an accepted plan for 400, and an accepted
    independent plan for 1000."""
    for module in (working_calendar_service, quotations_api, sales_orders_api, feasibility_record_service, quotation_readiness_service):
        monkeypatch.setattr(module, "now_jdk", lambda: MONDAY_9AM_KUWAIT)
    users = {}
    for username, role in (("salesman_a", TEAM_MEMBER), ("boss", ADMIN), ("planner", MANAGER), ("viewer", TEAM_MEMBER)):
        users[username] = User(
            organisation_id=organisation.id, role=role, full_name=username.title(), email=f"{username}@example.com",
            username=username, password_hash=hash_password("Str0ng!Pass"), is_active=True,
        )
        db_session.add(users[username])
    db_session.flush()
    for action in ("view", "manage"):
        db_session.add(RolePermission(organisation_id=organisation.id, role=MANAGER, module_key="production", action=action, scope="all"))
    db_session.add(UserPermission(organisation_id=organisation.id, user_id=users["viewer"].id, module_key="production", action="view", scope="all"))
    customer = Customer(
        organisation_id=organisation.id, code="300001", name="A Co", assigned_to_user_id=users["salesman_a"].id,
        phone="96511111111", address="Shuwaikh", payment_arrangement="after_delivery",
    )
    widget_product.min_selling_price, widget_product.max_selling_price = Decimal("90"), Decimal("110")
    machine_1.capacity_quantity, machine_1.capacity_period_hours = Decimal("500"), Decimal("8")
    organisation.production_hours_per_day = Decimal("8")
    db_session.add_all([customer, OrganisationHoliday(organisation_id=organisation.id, holiday_date=date(2026, 9, 30), description="Holiday")])
    db_session.flush()
    bom = Bom(organisation_id=organisation.id, product_id=widget_product.id, base_quantity=Decimal("1"), status=ACTIVE)
    db_session.add(bom)
    db_session.flush()
    db_session.add(BomComponent(bom_id=bom.id, raw_material_id=cement_raw_material.id, quantity=Decimal("2")))
    db_session.commit()
    finished_goods_inventory_service.receive_finished_goods(
        db_session, organisation_id=organisation.id, product_id=widget_product.id, warehouse_id=warehouse_1.id,
        quantity=Decimal("600"), unit_of_measure_id=widget_product.unit_of_measure_id, reference_type="test_seed",
        reference_id=1, created_by_user_id=None,
    )
    inventory_service.receive_stock(
        db_session, organisation_id=organisation.id, raw_material_id=cement_raw_material.id, warehouse_id=warehouse_1.id,
        quantity=Decimal("1000"), unit_of_measure_id=cement_raw_material.unit_of_measure_id, reference_type="test_seed",
        reference_id=1, created_by_user_id=None,
    )
    db_session.commit()

    a = _headers(client, "salesman_a")
    line = {"product_id": widget_product.id, "quantity": "1000", "unit_of_measure_id": widget_product.unit_of_measure_id, "unit_price": "100"}
    quotation = client.post("/api/quotations", json={"customer_id": customer.id, "requested_delivery_date": "2026-10-05", "lines": [line]}, headers=a).json()
    client.post(f"/api/quotations/{quotation['id']}/accept", headers=a)
    order = client.post(f"/api/quotations/{quotation['id']}/convert", headers=a).json()
    planner = _headers(client, "planner")
    requirement_id = db_session.query(ProductionRequirement.id).scalar()
    customer_plan = client.post("/api/production-plans", json={"source_type": "customer_demand", "production_requirement_id": requirement_id}, headers=planner).json()
    independent = client.post("/api/production-plans", json={"source_type": "independent", "product_id": widget_product.id, "planned_quantity": "1000"}, headers=planner).json()
    draft = client.post("/api/production-plans", json={"source_type": "independent", "product_id": widget_product.id, "planned_quantity": "50"}, headers=planner).json()
    for plan in (customer_plan, independent):
        assert client.post(f"/api/production-plans/{plan['id']}/plan", headers=planner).status_code == 200
    return order, customer_plan, independent, draft, machine_1


def _schedule(client, plan, day, quantity, username="planner", **extra):
    body = {"production_plan_id": plan["id"], "scheduled_date": day, "quantity": quantity, **extra}
    return client.post("/api/production-schedule", json=body, headers=_headers(client, username))


def _plan_view(client, plan):
    return client.get(f"/api/production-plans/{plan['id']}/schedule", headers=_headers(client, "viewer")).json()


def _day(client, day):
    [view] = client.get("/api/production-schedule/days", params={"start": day, "end": day}, headers=_headers(client, "viewer")).json()
    return view


def _inventory(db_session):
    db_session.expire_all()
    return (
        [r.quantity_on_hand for r in db_session.query(FinishedGoodsInventory)],
        [r.quantity_on_hand for r in db_session.query(RawMaterialInventory)],
        db_session.query(FinishedGoodsMovement).count(),
        db_session.query(StockMovement).count(),
    )


def test_a_plan_is_split_across_days_within_its_quantity_on_working_days_only(client, db_session, setup):
    order, customer_plan, independent, draft, machine = setup
    before = _inventory(db_session)
    assert _schedule(client, draft, MON, "10").status_code == 409  # a draft plan is not scheduled

    first = _schedule(client, customer_plan, MON, "150")
    assert first.status_code == 201, first.json()
    entry = first.json()
    assert (entry["machine_id"], entry["sequence"], entry["sales_order_number"], entry["production_requirement_id"], entry["late"]) == (
        machine.id, 1, order["order_number"], customer_plan["production_requirement_id"], False,
    )
    view = _plan_view(client, customer_plan)
    assert (_q(view, "planned_quantity", "scheduled_quantity", "unscheduled_quantity"), view["fully_scheduled"]) == ([400, 150, 250], False)
    assert "not_fully_scheduled" in view["exceptions"]
    assert _schedule(client, customer_plan, TUE, "250").status_code == 201
    view = _plan_view(client, customer_plan)
    assert (_q(view, "scheduled_quantity", "unscheduled_quantity"), view["fully_scheduled"]) == ([400, 0], True)
    # Never beyond the plan; the plan quantity is not raised.
    over = _schedule(client, customer_plan, THU, "1")
    assert over.status_code == 409 and "still unscheduled" in over.json()["error"]["message"]
    assert Decimal(client.get(f"/api/production-plans/{customer_plan['id']}", headers=_headers(client, "viewer")).json()["planned_quantity"]) == 400

    # Friday and the Wednesday holiday are not production days.
    for day in (FRI, WED):
        refused = _schedule(client, independent, day, "10")
        assert refused.status_code == 422 and "not a working day" in refused.json()["error"]["message"]

    # Scheduling touched no inventory and created no Production Order.
    assert _inventory(db_session) == before
    assert not any("production_order" in t for t in Base.metadata.tables)


def test_daily_capacity_load_remaining_and_overload(client, db_session, setup):
    _, customer_plan, independent, _, machine = setup
    _schedule(client, customer_plan, MON, "150")
    _schedule(client, independent, MON, "400")
    monday = _day(client, MON)
    assert monday["is_working_day"] is True
    [line] = monday["machines"]
    assert [e["sequence"] for e in line["entries"]] == [1, 2]
    assert [Decimal(line[k]) for k in ("capacity_quantity", "scheduled_load", "remaining_capacity", "overload_quantity")] == [500, 550, 0, 50]
    assert "capacity_overload" in _plan_view(client, independent)["exceptions"]
    _schedule(client, independent, TUE, "250")
    [tuesday] = _day(client, TUE)["machines"]
    assert [Decimal(tuesday[k]) for k in ("scheduled_load", "remaining_capacity", "overload_quantity")] == [250, 250, 0]
    # Non-working days show no production line; the independent entry has no Sales Order.
    assert _day(client, FRI) == {"date": FRI, "is_working_day": False, "machines": []}
    assert tuesday["entries"][0]["sales_order_number"] is None and tuesday["entries"][0]["source_type"] == "independent"

    # Without the hours setting, capacity is not configured -- never guessed.
    db_session.query(Organisation).update({Organisation.production_hours_per_day: None})
    db_session.commit()
    [monday] = _day(client, MON)["machines"]
    assert (monday["capacity_quantity"], monday["remaining_capacity"], monday["overload_quantity"]) == (None, None, None)
    assert "not configured" in monday["capacity_note"]


def test_late_schedules_are_flagged_and_required_by_never_moves(client, db_session, setup):
    order, customer_plan, _, _, _ = setup
    entry = _schedule(client, customer_plan, "2026-10-06", "400").json()  # the day after required-by
    assert (entry["required_by_date"], entry["late"]) == ("2026-10-05", True)
    assert "late" in _plan_view(client, customer_plan)["exceptions"]
    assert client.get(f"/api/sales-orders/{order['id']}", headers=_headers(client, "boss")).json()["requested_delivery_date"] == "2026-10-05"


def test_rescheduling_keeps_history_and_cancelling_an_entry_keeps_the_plan(client, db_session, setup):
    _, customer_plan, independent, _, _ = setup
    before = _inventory(db_session)
    entry = _schedule(client, customer_plan, TUE, "400").json()
    url = f"/api/production-schedule/{entry['id']}"
    moved = client.patch(url, json={"scheduled_date": THU, "quantity": "300", "reason": "Line maintenance"}, headers=_headers(client, "planner"))
    assert moved.status_code == 200 and (moved.json()["scheduled_date"], Decimal(moved.json()["quantity"])) == (THU, 300)
    [event] = db_session.query(AuditEvent).filter(AuditEvent.action == PRODUCTION_RESCHEDULED).all()
    assert "scheduled_date: 2026-09-29 -> 2026-10-01" in event.details and "quantity: 400 -> 300" in event.details
    assert "reason: Line maintenance" in event.details and event.actor_user_id
    assert client.patch(url, json={"scheduled_date": FRI}, headers=_headers(client, "planner")).status_code == 422
    assert client.patch(url, json={"quantity": "401"}, headers=_headers(client, "planner")).status_code == 409

    assert client.post(f"{url}/cancel", json={"reason": " "}, headers=_headers(client, "planner")).status_code == 422
    cancelled = client.post(f"{url}/cancel", json={"reason": "Customer delay"}, headers=_headers(client, "planner")).json()
    assert (cancelled["status"], cancelled["cancellation_reason"]) == ("cancelled", "Customer delay")
    view = _plan_view(client, customer_plan)
    assert (view["status"], _q(view, "scheduled_quantity", "unscheduled_quantity")) == ("planned", [0, 400])
    assert [e["status"] for e in view["entries"]] == ["cancelled"]  # kept
    assert client.patch(url, json={"quantity": "10"}, headers=_headers(client, "planner")).status_code == 409

    # Cancelling a whole plan leaves nothing executable behind.
    _schedule(client, independent, MON, "100")
    client.post(f"/api/production-plans/{independent['id']}/cancel", json={"reason": "Not needed"}, headers=_headers(client, "planner"))
    assert [e["status"] for e in _plan_view(client, independent)["entries"]] == ["cancelled"]
    assert db_session.query(AuditEvent).filter(AuditEvent.action == PRODUCTION_SCHEDULE_CANCELLED).count() == 2
    assert db_session.query(AuditEvent).filter(AuditEvent.action == PRODUCTION_SCHEDULED).count() == 2
    assert _inventory(db_session) == before


def test_only_production_managers_change_the_schedule(client, db_session, setup):
    _, customer_plan, _, _, _ = setup
    assert _schedule(client, customer_plan, MON, "10", username="viewer").status_code == 403
    entry = _schedule(client, customer_plan, MON, "10").json()
    viewer = _headers(client, "viewer")
    assert client.patch(f"/api/production-schedule/{entry['id']}", json={"quantity": "5"}, headers=viewer).status_code == 403
    assert client.post(f"/api/production-schedule/{entry['id']}/cancel", json={"reason": "x"}, headers=viewer).status_code == 403
    assert client.get("/api/production-schedule/days", params={"start": MON, "end": MON}, headers=viewer).status_code == 200
    assert client.get("/api/production-schedule/days", params={"start": MON, "end": MON}, headers=_headers(client, "salesman_a")).status_code == 403


def _q(view, *keys):
    return [Decimal(view[k]) for k in keys]
