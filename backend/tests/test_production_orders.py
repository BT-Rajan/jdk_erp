"""P5 -- Production Order foundation: production work formally issued to
the factory from a scheduled Production Plan. draft (editable) -> issued
(validated; production basis snapshotted; fixed) ; -> cancelled (reason).
Traceable Order -> Schedule -> Plan -> source demand; numbered YY2NNNN;
never touches inventory."""

import re
from datetime import datetime
from decimal import Decimal

import pytest

from app.api import quotations as quotations_api
from app.api import sales_orders as sales_orders_api
from app.core.roles import ADMIN, MANAGER, TEAM_MEMBER
from app.core.security import hash_password
from app.core.timezone import JDK_TIMEZONE
from app.models.audit_event import PRODUCTION_ORDER_CANCELLED, PRODUCTION_ORDER_CREATED, PRODUCTION_ORDER_ISSUED, AuditEvent
from app.models.bom import ACTIVE, Bom, BomComponent
from app.models.customer import Customer
from app.models.finished_goods_inventory import FinishedGoodsInventory, FinishedGoodsMovement
from app.models.inventory import RawMaterialInventory, StockMovement
from app.models.production_plan import ProductionPlan, ProductionPlanComponent
from app.models.production_requirement import ProductionRequirement
from app.models.raw_material import RawMaterial
from app.models.role_permission import RolePermission
from app.models.user import User
from app.models.user_permission import UserPermission
from app.services import (
    document_numbering,
    feasibility_record_service,
    finished_goods_inventory_service,
    inventory_service,
    quotation_readiness_service,
    working_calendar_service,
)

MONDAY_9AM_KUWAIT = datetime(2026, 9, 28, 9, 0, tzinfo=JDK_TIMEZONE)
MON, TUE = "2026-09-28", "2026-09-29"


def _headers(client, username):
    login = client.post("/api/auth/login", json={"username": username, "password": "Str0ng!Pass"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.fixture()
def setup(client, db_session, organisation, widget_product, cement_raw_material, warehouse_1, machine_1, monkeypatch):
    """A customer plan for 400 (scheduled Monday, 400) and an independent
    plan for 1000 (Monday 600, Tuesday 400). Widget BOM: 1 <- 2 kg Cement."""
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
    organisation.production_hours_per_day = Decimal("8")
    db_session.add(customer)
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
    a, planner = _headers(client, "salesman_a"), _headers(client, "planner")
    line = {"product_id": widget_product.id, "quantity": "1000", "unit_of_measure_id": widget_product.unit_of_measure_id, "unit_price": "100"}
    quotation = client.post("/api/quotations", json={"customer_id": customer.id, "requested_delivery_date": "2026-10-05", "lines": [line]}, headers=a).json()
    client.post(f"/api/quotations/{quotation['id']}/accept", headers=a)
    order = client.post(f"/api/quotations/{quotation['id']}/convert", headers=a).json()
    requirement_id = db_session.query(ProductionRequirement.id).scalar()
    customer_plan = client.post("/api/production-plans", json={"source_type": "customer_demand", "production_requirement_id": requirement_id}, headers=planner).json()
    independent = client.post("/api/production-plans", json={"source_type": "independent", "product_id": widget_product.id, "planned_quantity": "1000"}, headers=planner).json()
    entries = {}
    for plan, day, quantity, key in ((customer_plan, MON, "400", "customer"), (independent, MON, "600", "ind_mon"), (independent, TUE, "400", "ind_tue")):
        client.post(f"/api/production-plans/{plan['id']}/plan", headers=planner)
        body = {"production_plan_id": plan["id"], "scheduled_date": day, "quantity": quantity}
        response = client.post("/api/production-schedule", json=body, headers=planner)
        assert response.status_code == 201, response.json()
        entries[key] = response.json()
    return order, customer_plan, independent, entries, cement_raw_material, bom, machine_1


def _create(client, entry, username="planner", **extra):
    return client.post("/api/production-orders", json={"production_schedule_entry_id": entry["id"], **extra}, headers=_headers(client, username))


def _post(client, order, action, body=None, username="planner"):
    return client.post(f"/api/production-orders/{order['id']}/{action}", json=body, headers=_headers(client, username))


def _inventory(db_session):
    db_session.expire_all()
    return (
        [r.quantity_on_hand for r in db_session.query(FinishedGoodsInventory)],
        [r.quantity_on_hand for r in db_session.query(RawMaterialInventory)],
        db_session.query(FinishedGoodsMovement).count(),
        db_session.query(StockMovement).count(),
    )


def test_orders_are_created_from_the_schedule_and_trace_back_to_their_demand(client, db_session, setup):
    order, customer_plan, independent, entries, _, _, machine = setup
    before = _inventory(db_session)
    customer = _create(client, entries["customer"])
    assert customer.status_code == 201, customer.json()
    body = customer.json()
    assert re.fullmatch(r"\d{2}2\d{4}", body["order_number"]) and document_numbering.ESTABLISHED_TYPE_DIGITS["2"] == "Production Order"
    assert (body["status"], Decimal(body["quantity"]), body["scheduled_date"], body["machine_id"], body["production_line_name"]) == (
        "draft", 400, MON, machine.id, "Production Line 1",
    )
    # Production Order -> Schedule -> Plan -> Production Requirement -> Sales Order line.
    assert (body["production_schedule_entry_id"], body["production_plan_id"], body["plan_source_type"]) == (
        entries["customer"]["id"], customer_plan["id"], "customer_demand",
    )
    assert (body["production_requirement_id"], body["sales_order_number"], body["sales_order_line_number"], body["required_by_date"]) == (
        customer_plan["production_requirement_id"], order["order_number"], 1, "2026-10-05",
    )
    assert body["components"] == [] and body["bom_id"] is None  # snapshot only at issue

    # Independent production: no Sales Order at all.
    mon = _create(client, entries["ind_mon"]).json()
    tue = _create(client, entries["ind_tue"]).json()
    assert (mon["plan_source_type"], mon["sales_order_id"], mon["production_requirement_id"]) == ("independent", None, None)
    # Unique, sequential numbers from the existing numbering.
    numbers = [body["order_number"], mon["order_number"], tue["order_number"]]
    assert len(set(numbers)) == 3 and sorted(numbers) == numbers
    assert _inventory(db_session) == before


def test_draft_edits_stay_within_the_schedule_and_issue_snapshots_the_basis(client, db_session, setup):
    _, _, _, entries, cement, bom, _ = setup
    before = _inventory(db_session)
    first = _create(client, entries["ind_mon"], quantity="350").json()
    url = f"/api/production-orders/{first['id']}"
    planner = _headers(client, "planner")
    # Draft is editable, never beyond what the entry still has.
    assert client.patch(url, json={"quantity": "601"}, headers=planner).status_code == 409
    assert client.patch(url, json={"quantity": "0"}, headers=planner).status_code == 422
    assert Decimal(client.patch(url, json={"quantity": "500"}, headers=planner).json()["quantity"]) == 500
    second = _create(client, entries["ind_mon"])
    assert second.status_code == 201 and Decimal(second.json()["quantity"]) == 100
    assert _create(client, entries["ind_mon"], quantity="1").status_code == 409

    issued = _post(client, first, "issue")
    assert issued.status_code == 200, issued.json()
    body = issued.json()
    assert (body["status"], body["bom_id"], Decimal(body["bom_base_quantity"]), body["issued_at"] is not None) == ("issued", bom.id, 1, True)
    assert [(c["raw_material_id"], Decimal(c["quantity"]), c["unit_of_measure_id"], Decimal(c["required_quantity"])) for c in body["components"]] == [
        (cement.id, 2, cement.unit_of_measure_id, 1000),  # 2 kg x 500, in Cement's own unit
    ]
    # The master BOM changing later never reaches the issued order.
    db_session.query(BomComponent).update({BomComponent.quantity: Decimal("9")})
    db_session.commit()
    assert Decimal(client.get(url, headers=planner).json()["components"][0]["required_quantity"]) == 1000
    # Issued core data is fixed: no edit, no second issue.
    assert client.patch(url, json={"quantity": "400"}, headers=planner).status_code == 409
    assert _post(client, first, "issue").status_code == 409
    # The schedule under an active order cannot move or be cancelled from under it.
    entry_url = f"/api/production-schedule/{entries['ind_mon']['id']}"
    assert client.patch(entry_url, json={"scheduled_date": TUE}, headers=planner).status_code == 409
    assert client.post(f"{entry_url}/cancel", json={"reason": "x"}, headers=planner).status_code == 409
    assert _inventory(db_session) == before


def test_issue_refuses_an_invalid_basis_and_never_corrects_it(client, db_session, setup, mass_tonne_unit):
    _, _, independent, entries, cement, _, _ = setup
    tue = _create(client, entries["ind_tue"]).json()
    # A raw material whose unit no longer matches the plan's basis: refused, not converted.
    other_unit = mass_tonne_unit.id
    db_session.query(ProductionPlanComponent).update({ProductionPlanComponent.unit_of_measure_id: other_unit})
    db_session.commit()
    refused = _post(client, tue, "issue")
    assert refused.status_code == 409 and "unit has changed" in refused.json()["error"]["message"]
    # No BOM basis at all: refused.
    db_session.query(ProductionPlanComponent).delete()
    db_session.query(ProductionPlan).filter(ProductionPlan.id == independent["id"]).update({ProductionPlan.bom_id: None})
    db_session.commit()
    refused = _post(client, tue, "issue")
    assert refused.status_code == 409 and "BOM required" in refused.json()["error"]["message"]
    assert client.get(f"/api/production-orders/{tue['id']}", headers=_headers(client, "planner")).json()["status"] == "draft"
    assert db_session.get(RawMaterial, cement.id).unit_of_measure_id == cement.unit_of_measure_id


def test_cancellation_needs_a_reason_keeps_history_and_blocks_issue(client, db_session, setup):
    _, customer_plan, _, entries, _, _, _ = setup
    order = _create(client, entries["customer"]).json()
    assert _post(client, order, "issue").status_code == 200
    # The plan cannot be cancelled while it has an active Production Order.
    assert client.post(f"/api/production-plans/{customer_plan['id']}/cancel", json={"reason": "x"}, headers=_headers(client, "planner")).status_code == 409
    assert _post(client, order, "cancel", {"reason": " "}).status_code == 422
    cancelled = _post(client, order, "cancel", {"reason": "Wrong quantity"}).json()
    assert (cancelled["status"], cancelled["cancellation_reason"]) == ("cancelled", "Wrong quantity") and cancelled["cancelled_at"]
    assert _post(client, order, "issue").status_code == 409
    assert _post(client, order, "cancel", {"reason": "again"}).status_code == 409
    actions = [h["action"] for h in cancelled["history"]]
    assert actions == [PRODUCTION_ORDER_CREATED, PRODUCTION_ORDER_ISSUED, PRODUCTION_ORDER_CANCELLED]
    assert all(h["actor_user_id"] for h in cancelled["history"])
    assert "reason: Wrong quantity" in cancelled["history"][-1]["details"]
    # With the order cancelled, a correcting order may be raised for the same entry.
    assert _create(client, entries["customer"]).status_code == 201
    assert db_session.query(AuditEvent).filter(AuditEvent.entity_type == "production_order").count() == 4


def test_only_production_managers_create_issue_or_cancel(client, db_session, setup):
    _, _, _, entries, _, _, _ = setup
    assert _create(client, entries["ind_tue"], username="viewer").status_code == 403
    order = _create(client, entries["ind_tue"]).json()
    assert _post(client, order, "issue", username="viewer").status_code == 403
    assert _post(client, order, "cancel", {"reason": "x"}, username="viewer").status_code == 403
    assert client.patch(f"/api/production-orders/{order['id']}", json={"notes": "x"}, headers=_headers(client, "viewer")).status_code == 403
    assert client.get("/api/production-orders", headers=_headers(client, "viewer")).status_code == 200
    assert client.get("/api/production-orders", headers=_headers(client, "salesman_a")).status_code == 403
