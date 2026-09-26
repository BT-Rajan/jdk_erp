"""Sales S10: controlled quotation editing and the list/detail data the
Sales UI relies on -- scope on edit, server-side re-validation, stale
feasibility after a material edit, client-owned fields ignored, and
server-computed readiness on list rows."""

from datetime import date, datetime
from decimal import Decimal

import pytest

from app.api import quotations as quotations_api
from app.core.roles import ADMIN, MANAGER, TEAM_MEMBER
from app.core.security import hash_password
from app.core.timezone import JDK_TIMEZONE
from app.models.audit_event import QUOTATION_UPDATED, AuditEvent
from app.models.customer import Customer
from app.models.team import Team
from app.models.unit import UnitOfMeasure
from app.models.user import User
from app.models.user_team import UserTeam
from app.services import (
    feasibility_record_service,
    finished_goods_inventory_service,
    quotation_readiness_service,
    working_calendar_service,
)

MONDAY = date(2026, 9, 28)
CLOCK = {"now": datetime(2026, 9, 28, 9, 0, tzinfo=JDK_TIMEZONE)}


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


@pytest.fixture()
def setup(db_session, organisation, widget_product, warehouse_1, monkeypatch):
    """Clock at Monday 09:00 Kuwait (movable via CLOCK). Sales team: head,
    salesmen A and B with one customer each (A has two). Widget: 10 in
    FG, permitted price 90-110."""
    CLOCK["now"] = datetime(2026, 9, 28, 9, 0, tzinfo=JDK_TIMEZONE)
    for module in (working_calendar_service, quotations_api, feasibility_record_service, quotation_readiness_service):
        monkeypatch.setattr(module, "now_jdk", lambda: CLOCK["now"])
    team = Team(organisation_id=organisation.id, name="Sales", code="SALES", is_active=True)
    db_session.add(team)
    db_session.commit()
    users = {
        "head": _user(db_session, organisation, "head", MANAGER),
        "a": _user(db_session, organisation, "salesman_a", TEAM_MEMBER),
        "b": _user(db_session, organisation, "salesman_b", TEAM_MEMBER),
        "admin": _user(db_session, organisation, "boss", ADMIN),
    }
    db_session.add_all([UserTeam(user_id=users[k].id, team_id=team.id) for k in ("head", "a", "b")])
    customers = {
        "a": Customer(organisation_id=organisation.id, code="300001", name="Alpha Co", assigned_to_user_id=users["a"].id),
        "a2": Customer(organisation_id=organisation.id, code="300002", name="Apex Co", assigned_to_user_id=users["a"].id),
        "b": Customer(organisation_id=organisation.id, code="300003", name="Beta Co", assigned_to_user_id=users["b"].id),
    }
    db_session.add_all(customers.values())
    widget_product.min_selling_price = Decimal("90")
    widget_product.max_selling_price = Decimal("110")
    db_session.commit()
    finished_goods_inventory_service.receive_finished_goods(
        db_session, organisation_id=organisation.id, product_id=widget_product.id, warehouse_id=warehouse_1.id,
        quantity=Decimal("10"), unit_of_measure_id=widget_product.unit_of_measure_id, reference_type="test_seed",
        reference_id=1, created_by_user_id=None,
    )
    db_session.commit()
    return users, customers, widget_product


def _line(product, quantity="5", price="100", unit_id=None):
    return {"product_id": product.id, "quantity": quantity, "unit_of_measure_id": unit_id or product.unit_of_measure_id, "unit_price": price}


def _quote(client, customer, product, username="salesman_a", requested=MONDAY, **line):
    body = {"customer_id": customer.id, "requested_delivery_date": requested.isoformat(), "lines": [_line(product, **line)]}
    response = client.post("/api/quotations", json=body, headers=_headers(client, username))
    assert response.status_code == 201, response.json()
    return response.json()


def test_editing_follows_customer_scope(client, setup):
    users, customers, widget = setup
    mine = _quote(client, customers["a"], widget)
    theirs = _quote(client, customers["b"], widget, username="salesman_b")
    a = _headers(client, "salesman_a")

    assert client.patch(f"/api/quotations/{theirs['id']}", json={"lines": [_line(widget, "1")]}, headers=a).status_code == 404
    # Moving my quotation onto another salesman's customer is refused the same way.
    assert client.patch(f"/api/quotations/{mine['id']}", json={"customer_id": customers["b"].id}, headers=a).status_code == 404
    assert client.patch(f"/api/quotations/{mine['id']}", json={"customer_id": customers["a2"].id}, headers=a).status_code == 200
    # The Department Head can edit within the team.
    head_edit = client.patch(f"/api/quotations/{theirs['id']}", json={"lines": [_line(widget, "2")]}, headers=_headers(client, "head"))
    assert head_edit.status_code == 200


def test_edit_is_revalidated_and_repriced_on_the_server(client, db_session, organisation, setup):
    users, customers, widget = setup
    quotation = _quote(client, customers["a"], widget)
    url, a = f"/api/quotations/{quotation['id']}", _headers(client, "salesman_a")
    litre = UnitOfMeasure(organisation_id=organisation.id, name="Litre", code="L", is_active=True)
    db_session.add(litre)
    db_session.commit()

    assert client.patch(url, json={"lines": [_line(widget, unit_id=litre.id)]}, headers=a).status_code == 422
    assert client.patch(url, json={"lines": [{**_line(widget), "product_id": 999999}]}, headers=a).status_code == 422
    assert client.patch(url, json={"lines": [_line(widget, quantity="0")]}, headers=a).status_code == 422

    edited = client.patch(url, json={"lines": [_line(widget, "3", "120.5")]}, headers=a).json()
    assert edited["quotation_number"] == quotation["quotation_number"]
    assert Decimal(edited["total_amount"]) == Decimal("361.500")
    assert edited["price_approval_required"] is True and edited["lines"][0]["price_approval_required"] is True
    # Same-day, never checked: the operational condition outranks the commercial one.
    assert edited["readiness_status"] == "operational_assessment_required"
    assert db_session.query(AuditEvent).filter(AuditEvent.action == QUOTATION_UPDATED).count() == 1


def test_material_edit_makes_feasibility_stale(client, db_session, setup):
    users, customers, widget = setup
    quotation = _quote(client, customers["a"], widget, quantity="12")  # same day, FG short
    url, a, admin = f"/api/quotations/{quotation['id']}", _headers(client, "salesman_a"), _headers(client, "boss")
    check = client.post(f"{url}/feasibility-checks", headers=a).json()
    client.put(f"{url}/feasibility-checks/{check['id']}/decision", json={"decision": "approved", "reason": "ok"}, headers=admin)
    assert client.post(f"{url}/readiness", headers=a).json()["status"] == "ready"

    client.patch(url, json={"lines": [_line(widget, "11")]}, headers=a)
    readiness = client.post(f"{url}/readiness", headers=a).json()
    assert (readiness["status"], readiness["reason_codes"]) == ("operational_assessment_required", ["feasibility_stale"])
    assert client.get(f"{url}/feasibility-checks/{check['id']}", headers=a).json()["is_current"] is False


def test_client_cannot_set_server_owned_fields(client, db_session, setup):
    users, customers, widget = setup
    quotation = _quote(client, customers["a"], widget, price="150")
    response = client.patch(
        f"/api/quotations/{quotation['id']}",
        json={
            "quotation_number": "2649999",
            "total_amount": "1",
            "subtotal_amount": "1",
            "status": "accepted",
            "price_approval_required": False,
            "readiness_status": "ready",
            "price_decision": "approved",
            "created_by_user_id": users["admin"].id,
        },
        headers=_headers(client, "salesman_a"),
    ).json()
    for field in ("quotation_number", "total_amount", "subtotal_amount", "status", "created_by_user_id"):
        assert response[field] == quotation[field]
    assert response["price_approval_required"] is True
    assert response["price_decision"] is None
    assert response["readiness_status"] != "ready"


def test_list_rows_carry_server_readiness_and_scope(client, setup):
    users, customers, widget = setup
    ready_later = _quote(client, customers["a"], widget, requested=date(2026, 10, 5))
    needs_check = _quote(client, customers["a"], widget)
    _quote(client, customers["b"], widget, username="salesman_b")

    rows = client.get("/api/quotations", headers=_headers(client, "salesman_a")).json()["data"]
    by_id = {row["id"]: row for row in rows}
    assert set(by_id) == {ready_later["id"], needs_check["id"]}
    assert (by_id[ready_later["id"]]["delivery_window"], by_id[ready_later["id"]]["readiness_status"]) == ("more_than_2_working_days", "ready")
    assert by_id[needs_check["id"]]["readiness_status"] == "operational_assessment_required"
    assert by_id[needs_check["id"]]["customer_name"] == "Alpha Co" and by_id[needs_check["id"]]["created_by_name"] == "Salesman_A"

    # Search stays inside scope.
    assert client.get("/api/quotations", params={"q": "Beta"}, headers=_headers(client, "salesman_a")).json()["data"] == []

    # A requested date that has since passed is reported, not an error.
    CLOCK["now"] = datetime(2026, 9, 29, 9, 0, tzinfo=JDK_TIMEZONE)
    row = client.get(f"/api/quotations/{needs_check['id']}", headers=_headers(client, "salesman_a")).json()
    assert row["readiness_status"] == "operational_assessment_required"
    reasons = client.post(f"/api/quotations/{needs_check['id']}/readiness", headers=_headers(client, "salesman_a")).json()["reason_codes"]
    assert reasons == ["requested_date_passed"]
