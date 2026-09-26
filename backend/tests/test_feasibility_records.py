"""Sales S8: feasibility decision records -- persisted results, Admin-only
exception decisions that never alter the calculation, re-checks that
keep history, and stale results that can't be reused."""

import json
from datetime import date, datetime
from decimal import Decimal

import pytest

from app.api import quotations as quotations_api
from app.core.roles import ADMIN, MANAGER, TEAM_MEMBER
from app.core.security import hash_password
from app.core.timezone import JDK_TIMEZONE
from app.models.audit_event import FEASIBILITY_DECIDED, FEASIBILITY_RECORDED, AuditEvent
from app.models.customer import Customer
from app.models.feasibility_check import FeasibilityCheck
from app.models.quotation import Quotation
from app.models.team import Team
from app.models.user import User
from app.models.user_team import UserTeam
from app.services import feasibility_record_service, finished_goods_inventory_service, working_calendar_service

MONDAY = date(2026, 9, 28)
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


def _receive(db_session, organisation, product, warehouse, quantity, reference_id):
    finished_goods_inventory_service.receive_finished_goods(
        db_session, organisation_id=organisation.id, product_id=product.id, warehouse_id=warehouse.id,
        quantity=Decimal(quantity), unit_of_measure_id=product.unit_of_measure_id, reference_type="test_seed",
        reference_id=reference_id, created_by_user_id=None,
    )
    db_session.commit()


@pytest.fixture()
def setup(db_session, organisation, widget_product, warehouse_1, monkeypatch):
    """Clock fixed at Monday 09:00 Kuwait; Widget has 10 in FG."""
    for module in (working_calendar_service, quotations_api, feasibility_record_service):
        monkeypatch.setattr(module, "now_jdk", lambda: MONDAY_9AM_KUWAIT)
    team = Team(organisation_id=organisation.id, name="Sales", code="SALES", is_active=True)
    db_session.add(team)
    db_session.commit()
    users = {
        "head": _user(db_session, organisation, "head", MANAGER),
        "a": _user(db_session, organisation, "salesman_a", TEAM_MEMBER),
        "admin": _user(db_session, organisation, "boss", ADMIN),
    }
    db_session.add_all([UserTeam(user_id=users[k].id, team_id=team.id) for k in ("head", "a")])
    customer = Customer(organisation_id=organisation.id, code="300001", name="A Co", assigned_to_user_id=users["a"].id)
    db_session.add(customer)
    db_session.commit()
    _receive(db_session, organisation, widget_product, warehouse_1, "10", 1)
    return users, customer, widget_product


def _quote(client, customer, product, quantity, requested):
    body = {
        "customer_id": customer.id,
        "requested_delivery_date": requested.isoformat(),
        "lines": [{"product_id": product.id, "quantity": quantity, "unit_of_measure_id": product.unit_of_measure_id, "unit_price": "100"}],
    }
    response = client.post("/api/quotations", json=body, headers=_headers(client, "salesman_a"))
    assert response.status_code == 201, response.json()
    return response.json()["id"]


def _run(client, quotation_id, username="salesman_a"):
    response = client.post(f"/api/quotations/{quotation_id}/feasibility-checks", headers=_headers(client, username))
    assert response.status_code == 201, response.json()
    return response.json()


def test_results_are_persisted_with_their_inputs_and_reasons(client, db_session, setup):
    users, customer, widget = setup
    # Wednesday: within 2 working days, FG covers it.
    within = _run(client, _quote(client, customer, widget, "4", date(2026, 9, 30)))
    assert (within["state"], within["result"], within["delivery_window"]) == ("calculated", "servable", "within_2_working_days")
    assert within["calculation_basis"] == "within_2_feasibility/v1" and within["reason_codes"] == ["fg_sufficient"]
    assert [(l["product_id"], Decimal(l["quantity"])) for l in within["lines"]] == [(widget.id, Decimal("4"))]
    assert within["requested_delivery_date"] == "2026-09-30" and within["created_by_user_id"] == users["a"].id
    assert within["calculated_at"].startswith("2026-09-28T06:00") and within["is_current"] is True

    later = _run(client, _quote(client, customer, widget, "999", date(2026, 10, 5)))
    assert (later["state"], later["reason_codes"]) == ("calculated", ["no_check_required"])
    friday = _run(client, _quote(client, customer, widget, "1", date(2026, 10, 2)))
    assert (friday["state"], friday["result"]) == ("not_servable", "not_servable")
    assert db_session.query(AuditEvent).filter(AuditEvent.action == FEASIBILITY_RECORDED).count() == 3


def test_exception_needs_an_admin_decision_with_a_reason(client, setup):
    users, customer, widget = setup
    quotation_id = _quote(client, customer, widget, "12", MONDAY)  # same day, only 10 in FG
    check = _run(client, quotation_id)
    assert (check["state"], check["result"], check["reason_codes"]) == ("admin_override_required", "admin_override_required", ["fg_insufficient"])

    url = f"/api/quotations/{quotation_id}/feasibility-checks/{check['id']}/decision"
    for username in ("salesman_a", "head"):
        assert client.put(url, json={"decision": "approved", "reason": "ok"}, headers=_headers(client, username)).status_code == 403
    assert client.put(url, json={"decision": "approved", "reason": "  "}, headers=_headers(client, "boss")).status_code == 422
    assert client.get(f"/api/quotations/{quotation_id}/feasibility-checks/{check['id']}", headers=_headers(client, "salesman_a")).json()["state"] == "admin_override_required"


def test_admin_decisions_are_audited_and_leave_the_calculation_untouched(client, db_session, setup):
    users, customer, widget = setup
    quotation_id = _quote(client, customer, widget, "12", MONDAY)
    check = _run(client, quotation_id)
    url = f"/api/quotations/{quotation_id}/feasibility-checks/{check['id']}/decision"
    admin = _headers(client, "boss")

    approved = client.put(url, json={"decision": "approved", "reason": "Priority customer"}, headers=admin).json()
    assert (approved["state"], approved["decided_by_user_id"], approved["decision_reason"]) == ("approved", users["admin"].id, "Priority customer")
    rejected = client.put(url, json={"decision": "rejected", "reason": "Reconsidered"}, headers=admin).json()
    assert rejected["state"] == "rejected"

    for field in ("result", "failed_stage", "reason_codes", "stages", "calculated_at", "lines"):
        assert rejected[field] == check[field]
    events = db_session.query(AuditEvent).filter(AuditEvent.action == FEASIBILITY_DECIDED).order_by(AuditEvent.id).all()
    assert ["admin_override_required -> approved" in events[0].details, "approved -> rejected" in events[1].details] == [True, True]


def test_recheck_creates_a_new_result_and_keeps_the_old_one(client, db_session, organisation, warehouse_1, setup):
    users, customer, widget = setup
    quotation_id = _quote(client, customer, widget, "12", MONDAY)
    first = _run(client, quotation_id)
    client.put(
        f"/api/quotations/{quotation_id}/feasibility-checks/{first['id']}/decision",
        json={"decision": "approved", "reason": "Priority customer"},
        headers=_headers(client, "boss"),
    )
    _receive(db_session, organisation, widget, warehouse_1, "5", 2)  # stock now covers it

    second = _run(client, quotation_id, username="head")
    assert (second["state"], second["result"], second["created_by_user_id"]) == ("calculated", "servable", users["head"].id)

    history = client.get(f"/api/quotations/{quotation_id}/feasibility-checks", headers=_headers(client, "salesman_a")).json()
    assert [h["id"] for h in history] == [second["id"], first["id"]]
    old = history[1]
    assert (old["state"], old["result"], old["reason_codes"], old["is_current"]) == ("approved", "admin_override_required", ["fg_insufficient"], False)
    assert history[0]["is_current"] is True
    # A superseded result can't be decided on.
    stale = client.put(
        f"/api/quotations/{quotation_id}/feasibility-checks/{first['id']}/decision",
        json={"decision": "rejected", "reason": "x"},
        headers=_headers(client, "boss"),
    )
    assert stale.status_code == 409


def test_changed_request_makes_the_result_stale(client, db_session, setup):
    users, customer, widget = setup
    quotation_id = _quote(client, customer, widget, "12", MONDAY)
    check = _run(client, quotation_id)
    url = f"/api/quotations/{quotation_id}/feasibility-checks/{check['id']}"

    # No quotation edit exists yet; simulate a future workflow changing the quantity.
    quotation = db_session.get(Quotation, quotation_id)
    quotation.lines[0].quantity = Decimal("11")
    db_session.commit()

    assert client.get(url, headers=_headers(client, "salesman_a")).json()["is_current"] is False
    decision = client.put(f"{url}/decision", json={"decision": "approved", "reason": "x"}, headers=_headers(client, "boss"))
    assert decision.status_code == 409
    # The stored calculation still shows what was actually checked.
    stored = db_session.get(FeasibilityCheck, check["id"])
    assert (stored.lines[0].quantity, json.loads(stored.reason_codes)) == (Decimal("12"), ["fg_insufficient"])
